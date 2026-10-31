"""Business documents and their state machines.

PO:        draft -> confirmed -> partial -> received        (or cancelled)
SO:        draft -> reserved  -> shipped                    (or cancelled, releasing reservations)
Transfer:  draft -> in_transit -> done                      (via the virtual transit location)
Count:     open  -> applied                                 (variances become adjustment moves)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CountLine,
    CountStatus,
    CycleCount,
    Location,
    LocationKind,
    Lot,
    POStatus,
    PurchaseOrder,
    Quant,
    Reservation,
    SalesOrder,
    SOStatus,
    StockMove,
    Transfer,
    TransferStatus,
    User,
)
from .stock import (
    EPS,
    StockError,
    apply_move,
    pick_quants,
    site_location_ids,
    site_root,
    subtree_ids,
    virtual_location,
)


def _require(status, allowed, what: str):
    if status not in allowed:
        names = ", ".join(a.value for a in allowed)
        raise StockError(f"{what} is '{status.value}', expected one of: {names}")


# --------------------------------------------------------------------------- purchase orders

def confirm_po(db: Session, po: PurchaseOrder) -> PurchaseOrder:
    _require(po.status, [POStatus.draft], po.number)
    if not po.lines:
        raise StockError("cannot confirm an empty purchase order")
    po.status = POStatus.confirmed
    return po


def get_or_create_lot(db: Session, product_id: int, code: str, expiry: date | None) -> Lot:
    lot = db.scalar(select(Lot).where(Lot.product_id == product_id, Lot.code == code))
    if lot is None:
        lot = Lot(product_id=product_id, code=code, expiry_date=expiry)
        db.add(lot)
        db.flush()
    elif expiry and lot.expiry_date != expiry:
        raise StockError(f"lot {code} already exists with expiry {lot.expiry_date}")
    return lot


def receive_po(db: Session, po: PurchaseOrder, receipts: list[dict], user: User | None) -> list[StockMove]:
    """receipts: [{line_id, qty, lot_code?, expiry_date?, location_id?}]"""
    _require(po.status, [POStatus.confirmed, POStatus.partial], po.number)
    supplier = virtual_location(db, LocationKind.supplier)
    lines = {line.id: line for line in po.lines}
    moves = []
    for r in receipts:
        line = lines.get(r["line_id"])
        if line is None:
            raise StockError(f"line {r['line_id']} is not on {po.number}")
        qty = float(r["qty"])
        if qty <= EPS:
            continue
        if line.qty_received + qty > line.qty_ordered + EPS:
            raise StockError(
                f"{line.product.sku}: receiving {qty} would exceed ordered {line.qty_ordered}"
                f" (already received {line.qty_received})"
            )
        dst = db.get(Location, r["location_id"]) if r.get("location_id") else site_root(db, po.site_id)
        if dst is None or dst.site_id != po.site_id or dst.kind != LocationKind.internal:
            raise StockError("receiving location must be an internal location of the PO's site")
        lot = None
        if line.product.tracking.value == "lot":
            if not r.get("lot_code"):
                raise StockError(f"{line.product.sku} is lot-tracked: lot_code is required")
            lot = get_or_create_lot(db, line.product_id, r["lot_code"], r.get("expiry_date"))
        moves.append(
            apply_move(
                db, product=line.product, qty=qty, src=supplier, dst=dst, lot=lot,
                unit_cost=line.unit_cost, reference=po.number, reason="purchase receipt", user=user,
            )
        )
        line.qty_received = round(line.qty_received + qty, 6)
    if not moves:
        raise StockError("nothing to receive")
    done = all(line.qty_received + EPS >= line.qty_ordered for line in po.lines)
    po.status = POStatus.received if done else POStatus.partial
    return moves


def cancel_po(db: Session, po: PurchaseOrder) -> PurchaseOrder:
    _require(po.status, [POStatus.draft, POStatus.confirmed], po.number)
    po.status = POStatus.cancelled
    return po


# --------------------------------------------------------------------------- sales orders

def reserve_so(db: Session, so: SalesOrder) -> SalesOrder:
    """All-or-nothing reservation of every line, FEFO/FIFO across the site."""
    _require(so.status, [SOStatus.draft], so.number)
    if not so.lines:
        raise StockError("cannot reserve an empty sales order")
    loc_ids = site_location_ids(db, so.site_id)
    applied: list[tuple[Quant, float]] = []
    try:
        for line in so.lines:  # line by line, so two lines of one product can't double-book
            for p in pick_quants(db, line.product, loc_ids, line.qty):
                p.quant.reserved = round(p.quant.reserved + p.qty, 6)
                applied.append((p.quant, p.qty))
                line.reservations.append(Reservation(quant=p.quant, qty=p.qty))
    except StockError:
        for q, qty in applied:  # all-or-nothing: a shortage on line 3 releases lines 1-2
            q.reserved = round(q.reserved - qty, 6)
        for line in so.lines:
            line.reservations.clear()
        raise
    so.status = SOStatus.reserved
    return so


def ship_so(db: Session, so: SalesOrder, user: User | None) -> list[StockMove]:
    _require(so.status, [SOStatus.reserved], so.number)
    customer = virtual_location(db, LocationKind.customer)
    moves = []
    for line in so.lines:
        for res in list(line.reservations):
            q: Quant = res.quant
            line.reservations.remove(res)
            db.flush()  # drop the reservation row before the quant may be emptied and deleted
            moves.append(
                apply_move(
                    db, product=line.product, qty=res.qty, src=q.location, dst=customer, lot=q.lot,
                    reference=so.number, reason="sales delivery", user=user, from_reserved=res.qty,
                )
            )
    so.status = SOStatus.shipped
    return moves


def cancel_so(db: Session, so: SalesOrder) -> SalesOrder:
    _require(so.status, [SOStatus.draft, SOStatus.reserved], so.number)
    for line in so.lines:
        for res in list(line.reservations):
            res.quant.reserved = round(max(res.quant.reserved - res.qty, 0.0), 6)
            line.reservations.remove(res)
    so.status = SOStatus.cancelled
    return so


# --------------------------------------------------------------------------- transfers

def dispatch_transfer(db: Session, tr: Transfer, user: User | None) -> list[StockMove]:
    _require(tr.status, [TransferStatus.draft], tr.number)
    if tr.from_site_id == tr.to_site_id:
        raise StockError("a transfer needs two different sites")
    transit = virtual_location(db, LocationKind.transit)
    loc_ids = site_location_ids(db, tr.from_site_id)
    plan = [(line, pick_quants(db, line.product, loc_ids, line.qty)) for line in tr.lines]
    moves = []
    for line, picks in plan:
        for p in picks:
            moves.append(
                apply_move(
                    db, product=line.product, qty=p.qty, src=p.quant.location, dst=transit,
                    lot=p.quant.lot, reference=tr.number, reason="transfer dispatch", user=user,
                )
            )
    tr.status = TransferStatus.in_transit
    return moves


def receive_transfer(db: Session, tr: Transfer, user: User | None) -> list[StockMove]:
    """Replays the dispatch moves out of transit, so lots survive the trip."""
    _require(tr.status, [TransferStatus.in_transit], tr.number)
    transit = virtual_location(db, LocationKind.transit)
    dst = site_root(db, tr.to_site_id)
    sent = db.scalars(
        select(StockMove).where(StockMove.reference == tr.number, StockMove.to_location_id == transit.id)
    ).all()
    moves = [
        apply_move(
            db, product=m.product, qty=m.quantity, src=transit, dst=dst, lot=m.lot,
            unit_cost=m.unit_cost, reference=tr.number, reason="transfer receipt", user=user,
        )
        for m in sent
    ]
    tr.status = TransferStatus.done
    return moves


# --------------------------------------------------------------------------- cycle counts

def snapshot_count(db: Session, count: CycleCount) -> CycleCount:
    """Freeze the expected quantities of a location subtree into count lines."""
    ids = subtree_ids(db, count.location_id)
    agg: dict[tuple[int, int | None], float] = {}
    for q in db.scalars(select(Quant).where(Quant.location_id.in_(ids))):
        key = (q.product_id, q.lot_id)
        agg[key] = agg.get(key, 0.0) + q.quantity
    for (pid, lot_id), qty in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        count.lines.append(CountLine(product_id=pid, lot_id=lot_id, expected=round(qty, 6)))
    return count


def apply_count(db: Session, count: CycleCount, user: User | None) -> list[StockMove]:
    """Post the variance of every counted line as a move to/from 'adjustment'.

    Losses are taken from the subtree using the normal removal strategy;
    gains land in the counted location itself.
    """
    _require(count.status, [CountStatus.open], count.number)
    adj = virtual_location(db, LocationKind.adjustment)
    ids = subtree_ids(db, count.location_id)
    moves = []
    for line in count.lines:
        if line.counted is None:
            continue
        diff = round(line.counted - line.expected, 6)
        if abs(diff) <= EPS:
            continue
        if diff > 0:
            moves.append(
                apply_move(
                    db, product=line.product, qty=diff, src=adj, dst=count.location, lot=line.lot,
                    reference=count.number, reason="count gain", user=user,
                )
            )
            continue
        need = -diff
        stmt = select(Quant).where(Quant.product_id == line.product_id, Quant.location_id.in_(ids))
        stmt = stmt.where(Quant.lot_id.is_(None) if line.lot_id is None else Quant.lot_id == line.lot_id)
        for q in sorted(db.scalars(stmt), key=lambda q: (q.in_date, q.id)):
            take = min(q.available, need)
            if take <= EPS:
                continue
            moves.append(
                apply_move(
                    db, product=line.product, qty=take, src=q.location, dst=adj, lot=q.lot,
                    reference=count.number, reason="count loss", user=user,
                )
            )
            need = round(need - take, 6)
            if need <= EPS:
                break
        if need > EPS:
            raise StockError(f"{line.product.sku}: cannot post a loss of {-diff}, stock is reserved")
    count.status = CountStatus.applied
    return moves
