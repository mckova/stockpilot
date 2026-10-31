"""Analytics on top of the ledger: demand forecast, reorder points, ABC, dead stock,
replenishment suggestions and the dashboard.

Forecasting is deliberately transparent (no black box): simple exponential
smoothing of daily demand with a multiplicative day-of-week index. Safety stock
uses the textbook z * sigma * sqrt(lead time) at a 95% service level.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Location,
    LocationKind,
    Lot,
    POStatus,
    Product,
    PurchaseOrder,
    Quant,
    ReorderRule,
    SalesOrder,
    SOStatus,
    StockMove,
    utcnow,
)
from .stock import availability

Z_95 = 1.65
ALPHA = 0.3


def _today() -> date:
    return utcnow().date()


def daily_demand(db: Session, days: int = 90, site_id: int | None = None) -> dict[int, list[float]]:
    """product_id -> list of daily outgoing quantities (oldest first)."""
    start = _today() - timedelta(days=days - 1)
    customer_ids = select(Location.id).where(Location.kind == LocationKind.customer)
    stmt = (
        select(StockMove.product_id, StockMove.created_at, StockMove.quantity, StockMove.from_location_id)
        .where(StockMove.to_location_id.in_(customer_ids))
        .where(StockMove.created_at >= datetime.combine(start, datetime.min.time()))
    )
    site_of = dict(db.execute(select(Location.id, Location.site_id)).all())
    series: dict[int, list[float]] = defaultdict(lambda: [0.0] * days)
    for pid, ts, qty, src in db.execute(stmt):
        if site_id and site_of.get(src) != site_id:
            continue
        idx = (ts.date() - start).days
        if 0 <= idx < days:
            series[pid][idx] += qty
    return series


def forecast_series(history: list[float], horizon: int = 14, start: date | None = None) -> dict:
    """SES level + day-of-week seasonality. Returns level, sigma, and the horizon forecast."""
    n = len(history)
    if n == 0 or sum(history) == 0:
        return {"daily": 0.0, "sigma": 0.0, "forecast": [0.0] * horizon}
    start = start or (_today() - timedelta(days=n - 1))
    mean = sum(history) / n
    # day-of-week index, shrunk toward 1 when data is thin
    by_dow: dict[int, list[float]] = defaultdict(list)
    for i, v in enumerate(history):
        by_dow[(start + timedelta(days=i)).weekday()].append(v)
    idx = {}
    for d in range(7):
        vals = by_dow.get(d, [])
        raw = (sum(vals) / len(vals) / mean) if vals and mean > 0 else 1.0
        w = min(len(vals) / 8, 1.0)
        idx[d] = w * raw + (1 - w)
    # SES on de-seasonalised series
    level = history[0] / (idx[start.weekday()] or 1.0)
    errors = []
    for i, v in enumerate(history[1:], start=1):
        s = idx[(start + timedelta(days=i)).weekday()] or 1.0
        pred = level * s
        errors.append(v - pred)
        level = ALPHA * (v / s) + (1 - ALPHA) * level
    sigma = math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else 0.0
    first = start + timedelta(days=n)
    fc = [round(level * idx[(first + timedelta(days=h)).weekday()], 3) for h in range(horizon)]
    return {"daily": round(level, 3), "sigma": round(sigma, 3), "forecast": fc}


def product_insights(db: Session, site_id: int | None = None, days: int = 90) -> list[dict]:
    demand = daily_demand(db, days, site_id)
    avail = defaultdict(float)
    for row in availability(db, site_id=site_id):
        avail[row["product_id"]] += row["available"]
    last_out = dict(
        db.execute(
            select(StockMove.product_id, func.max(StockMove.created_at))
            .where(StockMove.to_location_id.in_(select(Location.id).where(Location.kind == LocationKind.customer)))
            .group_by(StockMove.product_id)
        ).all()
    )
    products = db.scalars(select(Product).where(Product.active.is_(True))).all()

    # ABC on consumption value
    value = {p.id: sum(demand.get(p.id, [])) * p.avg_cost for p in products}
    total = sum(value.values()) or 1.0
    abc, running = {}, 0.0
    for pid, v in sorted(value.items(), key=lambda kv: -kv[1]):
        running += v
        share = running / total
        abc[pid] = "A" if share <= 0.80 or running == v else ("B" if share <= 0.95 else "C")

    out = []
    for p in products:
        hist = demand.get(p.id, [0.0] * days)
        f = forecast_series(hist)
        lead = p.preferred_supplier.lead_time_days if p.preferred_supplier else 3
        safety = Z_95 * f["sigma"] * math.sqrt(lead)
        rop = f["daily"] * lead + safety
        a = avail.get(p.id, 0.0)
        cover = (a / f["daily"]) if f["daily"] > 0 else None
        lo = last_out.get(p.id)
        idle_days = (_today() - lo.date()).days if lo else None
        out.append(
            {
                "product_id": p.id,
                "sku": p.sku,
                "name": p.name,
                "abc": abc.get(p.id, "C"),
                "available": round(a, 3),
                "avg_daily_demand": f["daily"],
                "demand_sigma": f["sigma"],
                "forecast_14d": f["forecast"],
                "lead_time_days": lead,
                "safety_stock": round(safety, 2),
                "reorder_point": round(rop, 2),
                "days_of_cover": round(cover, 1) if cover is not None else None,
                "stockout_date": (_today() + timedelta(days=int(cover))).isoformat() if cover is not None else None,
                "dead_stock": a > 0 and (idle_days is None or idle_days >= 45),
                "risk": "stockout" if a <= rop and f["daily"] > 0 else ("overstock" if cover and cover > 120 else "ok"),
                "history_90d": [round(x, 3) for x in hist],
            }
        )
    return out


def replenishment(db: Session) -> list[dict]:
    """Min/max logic: if projected < min, order up to max in multiples."""
    bins = {(r["product_id"], r["site_id"]): r for r in availability(db)}
    ins = {r["product_id"]: r for r in product_insights(db)}
    out = []
    for rule in db.scalars(select(ReorderRule)).all():
        b = bins.get((rule.product_id, rule.site_id), {"on_hand": 0, "available": 0, "incoming": 0, "projected": 0})
        projected = b["projected"]
        qty = 0.0
        if projected < rule.min_qty:
            qty = rule.max_qty - projected
            m = rule.multiple or 1.0
            qty = math.ceil(qty / m - 1e-9) * m
        out.append(
            {
                "rule_id": rule.id,
                "product_id": rule.product_id,
                "sku": rule.product.sku,
                "name": rule.product.name,
                "site_id": rule.site_id,
                "site": rule.site.name,
                "min_qty": rule.min_qty,
                "max_qty": rule.max_qty,
                "multiple": rule.multiple,
                "on_hand": b["on_hand"],
                "incoming": b["incoming"],
                "projected": projected,
                "suggested_qty": qty,
                "route": "transfer" if rule.source_site_id else "buy",
                "source_site_id": rule.source_site_id,
                "source_site": rule.source_site.name if rule.source_site else None,
                "supplier_id": rule.product.preferred_supplier_id,
                "supplier": rule.product.preferred_supplier.name if rule.product.preferred_supplier else None,
                "unit_cost": rule.product.avg_cost,
                "forecast_reorder_point": ins.get(rule.product_id, {}).get("reorder_point"),
            }
        )
    return out


def dashboard(db: Session) -> dict:
    today = _today()
    value = db.scalar(
        select(func.coalesce(func.sum(Quant.quantity * Product.avg_cost), 0.0)).join(Product, Quant.product_id == Product.id)
    )
    units = db.scalar(select(func.coalesce(func.sum(Quant.quantity), 0.0)))
    skus = db.scalar(select(func.count(func.distinct(Quant.product_id))))
    expiring = db.execute(
        select(Lot, func.sum(Quant.quantity))
        .join(Quant, Quant.lot_id == Lot.id)
        .where(Lot.expiry_date.is_not(None), Lot.expiry_date <= today + timedelta(days=30))
        .group_by(Lot.id)
        .order_by(Lot.expiry_date)
    ).all()
    repl = [r for r in replenishment(db) if r["suggested_qty"] > 0]
    open_pos = db.scalar(
        select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status.in_([POStatus.confirmed, POStatus.partial]))
    )
    open_sos = db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.status == SOStatus.reserved))

    # 30-day movement series: inbound (from supplier) vs outbound (to customer), by value
    kinds = dict(db.execute(select(Location.id, Location.kind)).all())
    start = today - timedelta(days=29)
    series = {(start + timedelta(days=i)).isoformat(): {"in": 0.0, "out": 0.0} for i in range(30)}
    for ts, qty, cost, src, dst in db.execute(
        select(StockMove.created_at, StockMove.quantity, StockMove.unit_cost, StockMove.from_location_id, StockMove.to_location_id)
        .where(StockMove.created_at >= datetime.combine(start, datetime.min.time()))
    ):
        key = ts.date().isoformat()
        if key not in series:
            continue
        if kinds.get(src) == LocationKind.supplier:
            series[key]["in"] += qty * cost
        elif kinds.get(dst) == LocationKind.customer:
            series[key]["out"] += qty * cost
    return {
        "stock_value": round(value or 0, 2),
        "units_on_hand": round(units or 0, 2),
        "skus_in_stock": skus or 0,
        "open_purchase_orders": open_pos or 0,
        "orders_to_ship": open_sos or 0,
        "reorder_alerts": len(repl),
        "reorder_top": repl[:6],
        "expiring_lots": [
            {
                "lot": lot.code,
                "product_id": lot.product_id,
                "expiry_date": lot.expiry_date.isoformat(),
                "days_left": (lot.expiry_date - today).days,
                "quantity": round(q, 2),
            }
            for lot, q in expiring
        ],
        "movement_30d": [{"date": d, "inbound": round(v["in"], 2), "outbound": round(v["out"], 2)} for d, v in series.items()],
    }
