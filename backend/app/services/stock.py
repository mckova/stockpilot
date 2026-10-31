"""The stock engine: double-entry moves, quants, removal strategy, valuation.

Every quantity change goes through :func:`apply_move`. It writes one immutable
ledger row and updates the quants on whichever side of the move is a physical
(internal) location. Virtual locations (supplier, customer, adjustment,
transit) are not tracked as quants, so the ledger always balances.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Location,
    LocationKind,
    Lot,
    POLine,
    POStatus,
    Product,
    PurchaseOrder,
    Quant,
    Site,
    StockMove,
    Transfer,
    TransferLine,
    TransferStatus,
    User,
    utcnow,
)

EPS = 1e-9


class StockError(ValueError):
    """Business rule violation (insufficient stock, bad state transition ...)."""


# --------------------------------------------------------------------------- locations

def virtual_location(db: Session, kind: LocationKind) -> Location:
    loc = db.scalar(select(Location).where(Location.kind == kind, Location.site_id.is_(None)))
    if loc is None:
        loc = Location(code=kind.value.upper(), name=f"Virtual / {kind.value}", kind=kind)
        db.add(loc)
        db.flush()
    return loc


def site_root(db: Session, site_id: int) -> Location:
    loc = db.scalar(
        select(Location).where(
            Location.site_id == site_id,
            Location.parent_id.is_(None),
            Location.kind == LocationKind.internal,
        )
    )
    if loc is None:
        site = db.get(Site, site_id)
        if site is None:
            raise StockError(f"site {site_id} not found")
        loc = Location(site_id=site_id, code=site.code, name=f"{site.name} stock")
        db.add(loc)
        db.flush()
    return loc


def site_location_ids(db: Session, site_id: int) -> list[int]:
    return list(
        db.scalars(
            select(Location.id).where(
                Location.site_id == site_id, Location.kind == LocationKind.internal
            )
        )
    )


def subtree_ids(db: Session, location_id: int) -> list[int]:
    """The location and all of its descendants (breadth first)."""
    ids, frontier = [location_id], [location_id]
    while frontier:
        frontier = list(db.scalars(select(Location.id).where(Location.parent_id.in_(frontier))))
        ids.extend(frontier)
    return ids


# --------------------------------------------------------------------------- quants

def _quant(db: Session, product_id: int, location_id: int, lot_id: int | None) -> Quant | None:
    stmt = select(Quant).where(Quant.product_id == product_id, Quant.location_id == location_id)
    stmt = stmt.where(Quant.lot_id.is_(None) if lot_id is None else Quant.lot_id == lot_id)
    return db.scalar(stmt)


def on_hand_total(db: Session, product_id: int) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(Quant.quantity), 0.0)).where(Quant.product_id == product_id)))


def apply_move(
    db: Session,
    *,
    product: Product,
    qty: float,
    src: Location,
    dst: Location,
    reference: str,
    lot: Lot | None = None,
    unit_cost: float | None = None,
    reason: str | None = None,
    user: User | None = None,
    from_reserved: float = 0.0,
) -> StockMove:
    """Move ``qty`` of ``product`` from ``src`` to ``dst`` and log it.

    ``from_reserved`` is the part of ``qty`` that was already reserved on the
    source quant (shipping a reserved sales line); it is released together
    with the quantity instead of being checked against free stock.
    """
    if qty <= EPS:
        raise StockError("quantity must be positive")
    if src.id == dst.id:
        raise StockError("source and destination are the same location")
    if product.tracking.value == "lot" and lot is None and (
        src.kind == LocationKind.internal or dst.kind == LocationKind.internal
    ):
        raise StockError(f"{product.sku} is lot-tracked: a lot is required")

    # ----- valuation (AVCO): a receipt from a supplier re-weights the average
    if src.kind == LocationKind.supplier and dst.kind == LocationKind.internal:
        cost = product.avg_cost if unit_cost is None else unit_cost
        before = on_hand_total(db, product.id)
        total = before + qty
        product.avg_cost = round(((before * product.avg_cost) + qty * cost) / total, 6) if total > EPS else cost
        move_cost = cost
    else:
        move_cost = product.avg_cost if unit_cost is None else unit_cost

    lot_id = lot.id if lot else None

    if src.kind == LocationKind.internal:
        q = _quant(db, product.id, src.id, lot_id)
        free = (q.quantity - q.reserved) if q else 0.0
        if q is None or free + from_reserved + EPS < qty:
            raise StockError(
                f"insufficient stock of {product.sku} in {src.full_code}"
                f" (free {round(free, 3)}, requested {qty})"
            )
        q.quantity = round(q.quantity - qty, 6)
        q.reserved = round(max(q.reserved - from_reserved, 0.0), 6)
        if q.quantity <= EPS and q.reserved <= EPS:
            db.delete(q)

    if dst.kind == LocationKind.internal:
        q = _quant(db, product.id, dst.id, lot_id)
        if q is None:
            q = Quant(product_id=product.id, location_id=dst.id, lot_id=lot_id, quantity=0.0, reserved=0.0, in_date=utcnow())
            db.add(q)
        q.quantity = round(q.quantity + qty, 6)

    move = StockMove(
        product_id=product.id,
        lot_id=lot_id,
        quantity=qty,
        from_location_id=src.id,
        to_location_id=dst.id,
        unit_cost=round(move_cost, 6),
        reference=reference,
        reason=reason,
        user_id=user.id if user else None,
    )
    db.add(move)
    db.flush()
    return move


# --------------------------------------------------------------------------- removal strategy

@dataclass
class Pick:
    quant: Quant
    qty: float


def removal_order(product: Product):
    """FEFO for lot-tracked goods (earliest expiry first), FIFO otherwise.

    Ties break on in_date, then id, so the order is deterministic.
    """
    if product.tracking.value == "lot":
        def fefo(q: Quant):
            expiry = q.lot.expiry_date if q.lot and q.lot.expiry_date else date.max
            return (expiry, q.in_date, q.id)
        return fefo
    return lambda q: (q.in_date, q.id)


def pick_quants(db: Session, product: Product, location_ids: list[int], qty: float) -> list[Pick]:
    quants = list(
        db.scalars(
            select(Quant).where(Quant.product_id == product.id, Quant.location_id.in_(location_ids))
        )
    )
    quants.sort(key=removal_order(product))
    picks, remaining = [], qty
    for q in quants:
        if remaining <= EPS:
            break
        take = min(q.available, remaining)
        if take > EPS:
            picks.append(Pick(q, round(take, 6)))
            remaining = round(remaining - take, 6)
    if remaining > EPS:
        have = round(qty - remaining, 3)
        raise StockError(f"insufficient stock of {product.sku}: need {qty}, available {have}")
    return picks


# --------------------------------------------------------------------------- availability

def availability(db: Session, product_id: int | None = None, site_id: int | None = None) -> list[dict]:
    """Per product and site: on hand, reserved, available, incoming, projected."""
    loc_site = dict(db.execute(select(Location.id, Location.site_id).where(Location.kind == LocationKind.internal)).all())
    stmt = select(Quant.product_id, Quant.location_id, Quant.quantity, Quant.reserved)
    if product_id:
        stmt = stmt.where(Quant.product_id == product_id)
    agg: dict[tuple[int, int], dict] = defaultdict(lambda: {"on_hand": 0.0, "reserved": 0.0, "incoming": 0.0})
    for pid, lid, qty, res in db.execute(stmt):
        sid = loc_site.get(lid)
        if sid is None or (site_id and sid != site_id):
            continue
        row = agg[(pid, sid)]
        row["on_hand"] += qty
        row["reserved"] += res

    po_stmt = (
        select(POLine.product_id, PurchaseOrder.site_id, func.sum(POLine.qty_ordered - POLine.qty_received))
        .join(PurchaseOrder)
        .where(PurchaseOrder.status.in_([POStatus.draft, POStatus.confirmed, POStatus.partial]))
        .group_by(POLine.product_id, PurchaseOrder.site_id)
    )
    # inbound stock still on paper: drafts count too, so
    # generating replenishment drafts immediately satisfies the reorder rule
    tr_stmt = (
        select(TransferLine.product_id, Transfer.to_site_id, func.sum(TransferLine.qty))
        .join(Transfer)
        .where(Transfer.status.in_([TransferStatus.draft, TransferStatus.in_transit]))
        .group_by(TransferLine.product_id, Transfer.to_site_id)
    )
    for pid, sid, incoming in [*db.execute(po_stmt), *db.execute(tr_stmt)]:
        if (product_id and pid != product_id) or (site_id and sid != site_id):
            continue
        agg[(pid, sid)]["incoming"] += float(incoming or 0)

    out = []
    for (pid, sid), r in sorted(agg.items()):
        available = r["on_hand"] - r["reserved"]
        out.append(
            {
                "product_id": pid,
                "site_id": sid,
                "on_hand": round(r["on_hand"], 3),
                "reserved": round(r["reserved"], 3),
                "available": round(available, 3),
                "incoming": round(r["incoming"], 3),
                "projected": round(available + r["incoming"], 3),
            }
        )
    return out


def next_number(db: Session, model, prefix: str) -> str:
    count = db.scalar(select(func.count()).select_from(model)) or 0
    return f"{prefix}-{count + 1:04d}"
