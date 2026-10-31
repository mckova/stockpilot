"""Invariants of the stock engine, tested directly on the services."""
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.models import (
    CycleCount,
    Location,
    LocationKind,
    POLine,
    PurchaseOrder,
    Quant,
    SalesOrder,
    SOLine,
    StockMove,
    Transfer,
    TransferLine,
)
from app.services import documents as d
from app.services.insights import forecast_series
from app.services.stock import StockError, apply_move, availability, site_root, virtual_location


def _po(w, lines):
    po = PurchaseOrder(number=f"PO-{w['db'].query(PurchaseOrder).count() + 1}", supplier_id=w["sup"].id, site_id=w["wh"].id)
    for prod, qty, cost in lines:
        po.lines.append(POLine(product_id=prod.id, product=prod, qty_ordered=qty, unit_cost=cost))
    w["db"].add(po)
    w["db"].flush()
    d.confirm_po(w["db"], po)
    return po


def _receive(w, product, qty, cost, lot=None, expiry=None):
    po = _po(w, [(product, qty, cost)])
    r = {"line_id": po.lines[0].id, "qty": qty}
    if lot:
        r.update(lot_code=lot, expiry_date=expiry)
    d.receive_po(w["db"], po, [r], None)
    return po


def _ledger_balance(db, product_id):
    """On hand reconstructed from the ledger alone must equal the quants."""
    internal = select(Location.id).where(Location.kind == LocationKind.internal)
    inn = db.scalar(select(func.coalesce(func.sum(StockMove.quantity), 0)).where(StockMove.product_id == product_id, StockMove.to_location_id.in_(internal)))
    out = db.scalar(select(func.coalesce(func.sum(StockMove.quantity), 0)).where(StockMove.product_id == product_id, StockMove.from_location_id.in_(internal)))
    quants = db.scalar(select(func.coalesce(func.sum(Quant.quantity), 0)).where(Quant.product_id == product_id))
    return round(inn - out, 6), round(quants, 6)


def test_receipt_updates_moving_average_cost(world):
    _receive(world, world["mug"], 10, 4.0)
    _receive(world, world["mug"], 30, 8.0)
    assert world["mug"].avg_cost == pytest.approx((10 * 4 + 30 * 8) / 40)


def test_partial_receipt_then_complete(world):
    po = _po(world, [(world["mug"], 10, 1.0)])
    d.receive_po(world["db"], po, [{"line_id": po.lines[0].id, "qty": 4}], None)
    assert po.status.value == "partial"
    with pytest.raises(StockError, match="exceed"):
        d.receive_po(world["db"], po, [{"line_id": po.lines[0].id, "qty": 7}], None)
    d.receive_po(world["db"], po, [{"line_id": po.lines[0].id, "qty": 6}], None)
    assert po.status.value == "received"


def test_lot_tracked_requires_lot(world):
    po = _po(world, [(world["milk"], 5, 1.0)])
    with pytest.raises(StockError, match="lot"):
        d.receive_po(world["db"], po, [{"line_id": po.lines[0].id, "qty": 5}], None)


def test_fefo_reserves_earliest_expiry_first(world):
    today = date.today()
    _receive(world, world["milk"], 10, 1.0, lot="LATE", expiry=today + timedelta(days=20))
    _receive(world, world["milk"], 10, 1.0, lot="EARLY", expiry=today + timedelta(days=3))
    so = SalesOrder(number="SO-1", customer_id=world["cust"].id, site_id=world["wh"].id)
    so.lines.append(SOLine(product_id=world["milk"].id, product=world["milk"], qty=12, unit_price=5))
    world["db"].add(so)
    world["db"].flush()
    d.reserve_so(world["db"], so)
    picks = [(r.quant.lot.code, r.qty) for r in so.lines[0].reservations]
    assert picks == [("EARLY", 10), ("LATE", 2)]


def test_reserve_ship_and_cancel_release(world):
    db = world["db"]
    _receive(world, world["mug"], 10, 2.0)
    so = SalesOrder(number="SO-1", customer_id=world["cust"].id, site_id=world["wh"].id)
    so.lines.append(SOLine(product_id=world["mug"].id, product=world["mug"], qty=4, unit_price=10))
    db.add(so)
    db.flush()
    d.reserve_so(db, so)
    row = availability(db, site_id=world["wh"].id)[0]
    assert (row["on_hand"], row["reserved"], row["available"]) == (10, 4, 6)

    so2 = SalesOrder(number="SO-2", customer_id=world["cust"].id, site_id=world["wh"].id)
    so2.lines.append(SOLine(product_id=world["mug"].id, product=world["mug"], qty=7, unit_price=10))
    db.add(so2)
    db.flush()
    with pytest.raises(StockError, match="insufficient"):
        d.reserve_so(db, so2)  # only 6 free: reserved stock is protected

    d.ship_so(db, so, None)
    row = availability(db, site_id=world["wh"].id)[0]
    assert (row["on_hand"], row["reserved"]) == (6, 0)
    assert _ledger_balance(db, world["mug"].id) == (6, 6)


def test_failed_reservation_is_all_or_nothing(world):
    db = world["db"]
    _receive(world, world["mug"], 5, 1.0)
    so = SalesOrder(number="SO-1", customer_id=world["cust"].id, site_id=world["wh"].id)
    so.lines.append(SOLine(product_id=world["mug"].id, product=world["mug"], qty=3, unit_price=1))
    so.lines.append(SOLine(product_id=world["mug"].id, product=world["mug"], qty=3, unit_price=1))
    db.add(so)
    db.flush()
    with pytest.raises(StockError):
        d.reserve_so(db, so)
    assert db.scalar(select(func.sum(Quant.reserved))) == 0
    assert so.status.value == "draft"


def test_transfer_keeps_lots_through_transit(world):
    db = world["db"]
    exp = date.today() + timedelta(days=9)
    _receive(world, world["milk"], 8, 1.5, lot="L1", expiry=exp)
    tr = Transfer(number="TR-1", from_site_id=world["wh"].id, to_site_id=world["st"].id)
    tr.lines.append(TransferLine(product_id=world["milk"].id, product=world["milk"], qty=5))
    db.add(tr)
    db.flush()
    d.dispatch_transfer(db, tr, None)
    # while in transit the goods are on neither site
    assert sum(r["on_hand"] for r in availability(db)) == 3
    d.receive_transfer(db, tr, None)
    store_q = db.scalars(select(Quant).where(Quant.location_id == site_root(db, world["st"].id).id)).one()
    assert (store_q.quantity, store_q.lot.code) == (5, "L1")
    assert _ledger_balance(db, world["milk"].id) == (8, 8)


def test_cycle_count_posts_gain_and_loss(world):
    db = world["db"]
    _receive(world, world["mug"], 10, 3.0)
    root = site_root(db, world["wh"].id)
    cc = CycleCount(number="CC-1", location_id=root.id, location=root)
    db.add(cc)
    db.flush()
    d.snapshot_count(db, cc)
    assert [(line.expected) for line in cc.lines] == [10]
    cc.lines[0].counted = 7
    moves = d.apply_count(db, cc, None)
    assert [(m.quantity, m.to_location.kind.value, m.reason) for m in moves] == [(3, "adjustment", "count loss")]
    assert availability(db)[0]["on_hand"] == 7
    with pytest.raises(StockError):
        d.apply_count(db, cc, None)


def test_moves_reject_nonsense(world):
    db = world["db"]
    root = site_root(db, world["wh"].id)
    sup = virtual_location(db, LocationKind.supplier)
    with pytest.raises(StockError):
        apply_move(db, product=world["mug"], qty=0, src=sup, dst=root, reference="X")
    with pytest.raises(StockError):
        apply_move(db, product=world["mug"], qty=1, src=root, dst=root, reference="X")
    with pytest.raises(StockError, match="insufficient"):
        apply_move(db, product=world["mug"], qty=1, src=root, dst=virtual_location(db, LocationKind.customer), reference="X")


def test_forecast_flat_series_and_weekly_pattern():
    flat = forecast_series([5.0] * 60, horizon=7)
    assert flat["daily"] == pytest.approx(5.0)
    assert all(v == pytest.approx(5.0) for v in flat["forecast"])
    start = date(2026, 1, 5)  # a Monday
    weekly = [10.0 if (start + timedelta(days=i)).weekday() == 4 else 2.0 for i in range(84)]
    f = forecast_series(weekly, horizon=7, start=start)
    first = start + timedelta(days=84)
    friday = [i for i in range(7) if (first + timedelta(days=i)).weekday() == 4][0]
    assert f["forecast"][friday] == max(f["forecast"])
    assert forecast_series([], 3)["forecast"] == [0.0, 0.0, 0.0]
