"""Cycle counts, reorder rules, replenishment and analytics."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas as s
from ..auth import current_user, require
from ..db import get_db
from ..models import (
    CountStatus,
    CycleCount,
    Location,
    LocationKind,
    Partner,
    POLine,
    Product,
    PurchaseOrder,
    ReorderRule,
    Role,
    Site,
    Transfer,
    TransferLine,
    User,
    utcnow,
)
from ..services import documents as d
from ..services import insights
from ..services.stock import next_number

router = APIRouter(prefix="/api")


def _get(db: Session, model, oid: int):
    obj = db.get(model, oid)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {oid} not found")
    return obj


# --------------------------------------------------------------------------- cycle counts

@router.get("/counts")
def list_counts(db: Session = Depends(get_db), _=Depends(current_user)):
    return [s.count_out(c) for c in db.scalars(select(CycleCount).order_by(CycleCount.id.desc()))]


@router.post("/counts", status_code=201)
def create_count(body: s.CountIn, db: Session = Depends(get_db), _=Depends(require(Role.clerk))):
    loc = _get(db, Location, body.location_id)
    if loc.kind != LocationKind.internal:
        raise HTTPException(422, "only physical locations can be counted")
    c = CycleCount(number=next_number(db, CycleCount, "CC"), location_id=loc.id)
    db.add(c)
    d.snapshot_count(db, c)
    db.commit()
    return s.count_out(c)


@router.put("/counts/{oid}")
def enter_counts(oid: int, body: list[s.CountEntry], db: Session = Depends(get_db), _=Depends(require(Role.clerk))):
    c = _get(db, CycleCount, oid)
    if c.status != CountStatus.open:
        raise HTTPException(409, f"{c.number} is already applied")
    lines = {line.id: line for line in c.lines}
    for e in body:
        if e.line_id not in lines:
            raise HTTPException(422, f"line {e.line_id} is not on {c.number}")
        lines[e.line_id].counted = e.counted
    db.commit()
    return s.count_out(c)


@router.post("/counts/{oid}/apply")
def apply_count(oid: int, db: Session = Depends(get_db), user: User = Depends(require(Role.manager))):
    c = _get(db, CycleCount, oid)
    d.apply_count(db, c, user)
    db.commit()
    return s.count_out(c)


# --------------------------------------------------------------------------- reorder rules & replenishment

@router.get("/reorder-rules")
def list_rules(db: Session = Depends(get_db), _=Depends(current_user)):
    return [s.rule_out(r) for r in db.scalars(select(ReorderRule).order_by(ReorderRule.site_id, ReorderRule.product_id))]


@router.post("/reorder-rules", status_code=201)
def upsert_rule(body: s.RuleIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    if body.max_qty < body.min_qty:
        raise HTTPException(422, "max_qty must be >= min_qty")
    if body.source_site_id is not None and body.source_site_id == body.site_id:
        raise HTTPException(422, "a site cannot replenish from itself")
    _get(db, Product, body.product_id)
    _get(db, Site, body.site_id)
    r = db.scalar(select(ReorderRule).where(ReorderRule.product_id == body.product_id, ReorderRule.site_id == body.site_id))
    if r is None:
        r = ReorderRule(**body.model_dump())
        db.add(r)
    else:
        r.min_qty, r.max_qty, r.multiple, r.source_site_id = body.min_qty, body.max_qty, body.multiple, body.source_site_id
    db.commit()
    return s.rule_out(r)


@router.get("/replenishment")
def get_replenishment(db: Session = Depends(get_db), _=Depends(current_user)):
    return insights.replenishment(db)


@router.post("/replenishment/generate", status_code=201)
def generate_pos(body: s.GeneratePOIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    """Turn suggestions into draft documents: POs per (supplier, site) for 'buy'
    rules and transfers per (source, destination) for 'transfer' rules."""
    todo = [r for r in insights.replenishment(db) if r["suggested_qty"] > 0]
    if body.rule_ids is not None:
        todo = [r for r in todo if r["rule_id"] in set(body.rule_ids)]
    moves: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in [r for r in todo if r["route"] == "transfer"]:
        moves[(r["source_site_id"], r["site_id"])].append(r)
    todo = [r for r in todo if r["route"] == "buy"]
    missing = [r["sku"] for r in todo if r["supplier_id"] is None]
    if missing:
        raise HTTPException(422, f"no preferred supplier for: {', '.join(missing)}")
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in todo:
        groups[(r["supplier_id"], r["site_id"])].append(r)
    created = []
    for (sup, site), rows in groups.items():
        lead = db.get(Partner, sup).lead_time_days
        po = PurchaseOrder(
            number=next_number(db, PurchaseOrder, "PO"), supplier_id=sup, site_id=site,
            expected_date=(utcnow() + timedelta(days=lead)).date(), note="generated from reorder rules",
        )
        for r in rows:
            po.lines.append(POLine(product_id=r["product_id"], qty_ordered=r["suggested_qty"], unit_cost=round(r["unit_cost"], 2)))
        db.add(po)
        db.flush()
        created.append(po)
    transfers = []
    for (src, dst), rows in moves.items():
        t = Transfer(number=next_number(db, Transfer, "TR"), from_site_id=src, to_site_id=dst)
        t.lines = [TransferLine(product_id=r["product_id"], qty=r["suggested_qty"]) for r in rows]
        db.add(t)
        db.flush()
        transfers.append(t)
    db.commit()
    return {"purchase_orders": [s.po_out(po) for po in created], "transfers": [s.transfer_out(t) for t in transfers]}


# --------------------------------------------------------------------------- analytics

@router.get("/insights")
def get_insights(site_id: int | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    return insights.product_insights(db, site_id=site_id)


@router.get("/dashboard")
def get_dashboard(site_id: int | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    return insights.dashboard(db, site_id=site_id)
