"""Demo data: a fictional specialty-food distributor with one warehouse and two
stores, and 90 days of simulated operations so forecasts and charts have
something real to work with. Every quantity goes through the same services
the API uses, then the timestamps are back-dated.

    python -m app.seed            # (re)creates stockpilot.db
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .auth import hash_password
from .db import Base, SessionLocal, engine
from .models import (
    Category,
    CycleCount,
    Location,
    Partner,
    POLine,
    Product,
    PurchaseOrder,
    Quant,
    ReorderRule,
    Role,
    SalesOrder,
    Site,
    SiteKind,
    SOLine,
    StockMove,
    Tracking,
    Transfer,
    TransferLine,
    User,
    utcnow,
)
from .services import documents as d
from .services.stock import StockError, next_number, site_location_ids, site_root

DAYS = 90

SUPPLIERS = [
    ("Golan Roasters", 4), ("Emek Dairy Co-op", 2), ("Negev Olive Press", 6), ("Carmel Kitchenware", 10),
]
# sku, name, category, supplier idx, cost, price, lot-tracked, shelf-life days, base daily demand per store
CATALOG = [
    ("COF-ESP-1K", "Espresso beans 1kg", "Coffee", 0, 62.0, 109.0, True, 180, 6),
    ("COF-FIL-500", "Filter roast 500g", "Coffee", 0, 31.0, 54.0, True, 180, 5),
    ("COF-DEC-500", "Decaf roast 500g", "Coffee", 0, 34.0, 59.0, True, 180, 1.2),
    ("COF-CAP-50", "Coffee capsules x50", "Coffee", 0, 48.0, 89.0, True, 365, 3),
    ("DRY-MLK-1L", "Barista milk 1L", "Dairy", 1, 6.2, 11.9, True, 21, 14),
    ("DRY-OAT-1L", "Oat drink 1L", "Dairy", 1, 7.8, 14.5, True, 120, 8),
    ("DRY-BUT-200", "Cultured butter 200g", "Dairy", 1, 9.5, 17.9, True, 45, 4),
    ("DRY-LAB-250", "Labneh 250g", "Dairy", 1, 7.1, 13.5, True, 18, 5),
    ("OIL-EVO-750", "Extra virgin olive oil 750ml", "Pantry", 2, 29.0, 52.0, True, 540, 4),
    ("OIL-EVO-3L", "Extra virgin olive oil 3L", "Pantry", 2, 98.0, 169.0, True, 540, 1),
    ("PAN-TAH-500", "Raw tahini 500g", "Pantry", 2, 12.5, 24.0, True, 365, 6),
    ("PAN-ZAA-100", "Za'atar blend 100g", "Pantry", 2, 6.0, 14.0, False, 0, 3),
    ("PAN-HON-350", "Wildflower honey 350g", "Pantry", 2, 22.0, 39.0, False, 0, 2),
    ("KIT-MUG-350", "Stoneware mug 350ml", "Kitchenware", 3, 14.0, 39.0, False, 0, 1.5),
    ("KIT-FIL-100", "Paper filters x100", "Kitchenware", 3, 5.5, 14.9, False, 0, 3),
    ("KIT-MOK-6", "Moka pot 6 cups", "Kitchenware", 3, 68.0, 149.0, False, 0, 0.4),
    ("KIT-GRN-01", "Hand grinder", "Kitchenware", 3, 120.0, 249.0, False, 0, 0.25),
    ("KIT-TMP-58", "Espresso tamper 58mm", "Kitchenware", 3, 35.0, 79.0, False, 0, 0.0),  # dead stock
]
DOW = [1.0, 0.9, 0.95, 1.05, 1.35, 1.25, 0.6]  # Mon..Sun


def _backdate(db: Session, since_id: int, when: datetime) -> None:
    db.execute(update(StockMove).where(StockMove.id > since_id).values(created_at=when))


def _last_move_id(db: Session) -> int:
    return db.scalar(select(StockMove.id).order_by(StockMove.id.desc()).limit(1)) or 0


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth; fine for small lambdas
    if lam <= 0:
        return 0
    import math

    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def seed(db: Session, rng_seed: int = 7) -> None:
    rng = random.Random(rng_seed)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    users = [
        User(email="admin@stockpilot.dev", name="Noa Admin", role=Role.admin, password_hash=hash_password("admin123")),
        User(email="manager@stockpilot.dev", name="Eli Manager", role=Role.manager, password_hash=hash_password("manager123")),
        User(email="clerk@stockpilot.dev", name="Dana Clerk", role=Role.clerk, password_hash=hash_password("clerk123")),
    ]
    db.add_all(users)
    admin, manager, clerk = users

    wh = Site(code="WH1", name="Central Warehouse", kind=SiteKind.warehouse, city="Modi'in")
    st1 = Site(code="TLV", name="Tel Aviv Store", kind=SiteKind.store, city="Tel Aviv")
    st2 = Site(code="HFA", name="Haifa Store", kind=SiteKind.store, city="Haifa")
    db.add_all([wh, st1, st2])
    db.flush()

    root = site_root(db, wh.id)
    for zone, zname in [("A", "Ambient"), ("C", "Cold room"), ("K", "Kitchenware")]:
        z = Location(site_id=wh.id, parent_id=root.id, code=zone, name=f"Zone {zone} - {zname}")
        db.add(z)
        db.flush()
        for i in range(1, 4):
            db.add(Location(site_id=wh.id, parent_id=z.id, code=f"{zone}{i:02d}", name=f"Rack {zone}{i:02d}"))
    for st in (st1, st2):
        r = site_root(db, st.id)
        db.add(Location(site_id=st.id, parent_id=r.id, code="FLOOR", name="Sales floor"))
        db.add(Location(site_id=st.id, parent_id=r.id, code="BACK", name="Back room"))
    db.flush()

    sups = [Partner(name=n, kind="supplier", email=f"orders@{n.split()[0].lower()}.example", lead_time_days=lt) for n, lt in SUPPLIERS]
    custs = [Partner(name=n, kind="customer") for n in ["Walk-in (Tel Aviv)", "Walk-in (Haifa)", "Cafe Shalva", "Hotel Yam B2B"]]
    db.add_all(sups + custs)
    cats = {name: Category(name=name) for name in {c[2] for c in CATALOG}}
    db.add_all(cats.values())
    db.flush()

    products: list[tuple[Product, dict]] = []
    for i, (sku, name, cat, si, cost, price, lot, life, dem) in enumerate(CATALOG):
        p = Product(
            sku=sku, name=name, barcode=f"729{1000000000 + i * 7919:010d}", category_id=cats[cat].id,
            tracking=Tracking.lot if lot else Tracking.none, sale_price=price, avg_cost=cost,
            preferred_supplier_id=sups[si].id, uom="unit",
        )
        db.add(p)
        products.append((p, {"cost": cost, "life": life, "demand": dem, "supplier": sups[si]}))
    db.flush()

    start = utcnow().replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=DAYS)
    lot_seq = [0]

    def receive_po(po: PurchaseOrder, when: datetime, partial: float = 1.0) -> None:
        receipts = []
        for line in po.lines:
            info = dict(products)[line.product]
            qty = round(line.qty_ordered * partial)
            if qty <= 0:
                continue
            r = {"line_id": line.id, "qty": qty}
            if line.product.tracking == Tracking.lot:
                lot_seq[0] += 1
                r["lot_code"] = f"L{when:%y%m%d}-{lot_seq[0]:03d}"
                r["expiry_date"] = (when + timedelta(days=info["life"])).date()
            receipts.append(r)
        mark = _last_move_id(db)
        d.receive_po(db, po, receipts, clerk)
        _backdate(db, mark, when)

    def make_po(supplier: Partner, lines: list[tuple[Product, float]], when: datetime) -> PurchaseOrder:
        po = PurchaseOrder(number=next_number(db, PurchaseOrder, "PO"), supplier_id=supplier.id, site_id=wh.id,
                           expected_date=(when + timedelta(days=supplier.lead_time_days)).date())
        for p, q in lines:
            po.lines.append(POLine(product_id=p.id, product=p, qty_ordered=q, unit_cost=round(dict(products)[p]["cost"] * rng.uniform(0.95, 1.06), 2)))
        db.add(po)
        db.flush()
        po.created_at = when
        d.confirm_po(db, po)
        return po

    # opening stock
    by_sup: dict[int, list[tuple[Product, float]]] = {}
    for p, info in products:
        q = max(round(info["demand"] * 2 * 24 + 20, -1), 30)
        by_sup.setdefault(info["supplier"].id, []).append((p, q))
    for sup in sups:
        receive_po(make_po(sup, by_sup[sup.id], start - timedelta(days=5)), start - timedelta(days=1))

    pending: list[tuple[datetime, PurchaseOrder]] = []
    store_target = {p.id: max(info["demand"] * 9, 0) for p, info in products}

    for day in range(DAYS):
        now = start + timedelta(days=day)
        dow = DOW[now.weekday()]

        # incoming supplier deliveries
        for due, po in [x for x in pending if x[0] <= now]:
            receive_po(po, due)
            pending.remove((due, po))

        # weekly replenishment of the stores from the warehouse (Sun)
        if now.weekday() in (2, 6) or day == 0:  # Wed + Sun
            for st in (st1, st2):
                tr = Transfer(number=next_number(db, Transfer, "TR"), from_site_id=wh.id, to_site_id=st.id)
                for p, info in products:
                    have = sum(q.quantity for q in db.scalars(select(Quant).where(Quant.product_id == p.id, Quant.location_id.in_(site_location_ids(db, st.id)))))
                    need = round(store_target[p.id] - have)
                    if need > 0:
                        tr.lines.append(TransferLine(product_id=p.id, product=p, qty=need))
                if not tr.lines:
                    continue
                db.add(tr)
                db.flush()
                tr.created_at = now
                for line in list(tr.lines):  # trim lines the warehouse can't cover
                    free = sum(q.available for q in db.scalars(select(Quant).where(Quant.product_id == line.product_id, Quant.location_id.in_(site_location_ids(db, wh.id)))))
                    line.qty = min(line.qty, round(free))
                    if line.qty <= 0:
                        tr.lines.remove(line)
                db.flush()
                mark = _last_move_id(db)
                d.dispatch_transfer(db, tr, clerk)
                _backdate(db, mark, now + timedelta(hours=1))
                mark = _last_move_id(db)
                d.receive_transfer(db, tr, clerk)
                _backdate(db, mark, now + timedelta(hours=5))

        # store sales
        for st, cust in ((st1, custs[0]), (st2, custs[1])):
            loc_ids = site_location_ids(db, st.id)
            so = SalesOrder(number=next_number(db, SalesOrder, "SO"), customer_id=cust.id, site_id=st.id)
            for p, info in products:
                q = _poisson(rng, info["demand"] * dow * (1.15 if st is st1 else 0.85))
                free = sum(x.available for x in db.scalars(select(Quant).where(Quant.product_id == p.id, Quant.location_id.in_(loc_ids))))
                q = min(q, int(free))
                if q > 0:
                    so.lines.append(SOLine(product_id=p.id, product=p, qty=q, unit_price=p.sale_price))
            if not so.lines:
                continue
            db.add(so)
            db.flush()
            so.created_at = now + timedelta(hours=10)
            d.reserve_so(db, so)
            mark = _last_move_id(db)
            d.ship_so(db, so, clerk)
            _backdate(db, mark, now + timedelta(hours=rng.randint(10, 19)))

        # warehouse purchasing every 10 days, based on a simple cover target
        if day % 10 == 5:
            for sup in sups:
                lines = []
                for p, info in products:
                    if info["supplier"] is not sup or info["demand"] == 0:
                        continue
                    have = sum(q.quantity for q in db.scalars(select(Quant).where(Quant.product_id == p.id)))
                    target = info["demand"] * 2 * (16 + sup.lead_time_days)
                    if have < target:
                        lines.append((p, round(target - have + 10, -1)))
                if lines:
                    po = make_po(sup, lines, now)
                    pending.append((now + timedelta(days=sup.lead_time_days), po))
        db.flush()

    # ---- leave the demo in an interesting state --------------------------------------
    if pending:
        receive_po(pending[0][1], utcnow() - timedelta(hours=3), partial=0.5)

    # a B2B order waiting to ship, reserved from the warehouse (FEFO picks)
    pmap = {p.sku: p for p, _ in products}
    so = SalesOrder(number=next_number(db, SalesOrder, "SO"), customer_id=custs[3].id, site_id=wh.id)
    for sku, q in [("COF-ESP-1K", 12), ("DRY-MLK-1L", 40), ("OIL-EVO-750", 10)]:
        so.lines.append(SOLine(product_id=pmap[sku].id, product=pmap[sku], qty=q, unit_price=pmap[sku].sale_price * 0.85))
    db.add(so)
    db.flush()
    try:
        d.reserve_so(db, so)
    except StockError:
        pass
    # a draft order for Cafe Shalva
    so2 = SalesOrder(number=next_number(db, SalesOrder, "SO"), customer_id=custs[2].id, site_id=wh.id)
    so2.lines.append(SOLine(product_id=pmap["COF-FIL-500"].id, product=pmap["COF-FIL-500"], qty=20, unit_price=48.0))
    db.add(so2)

    # dead stock + a short-dated lot to show expiry alerts
    tamper_po = make_po(sups[3], [(pmap["KIT-TMP-58"], 25)], start - timedelta(days=3))
    receive_po(tamper_po, start)
    short = make_po(sups[1], [(pmap["DRY-LAB-250"], 30)], utcnow() - timedelta(days=15))
    mark = _last_move_id(db)
    d.receive_po(db, short, [{"line_id": short.lines[0].id, "qty": 30, "lot_code": "L-SHORT-01",
                              "expiry_date": (utcnow() + timedelta(days=4)).date()}], clerk)
    _backdate(db, mark, utcnow() - timedelta(days=14))

    # reorder rules: warehouse for everything, stores for the fast movers
    for p, info in products:
        dem = info["demand"] * 2
        lt = info["supplier"].lead_time_days
        mn = round(dem * (lt + 4))
        db.add(ReorderRule(product_id=p.id, site_id=wh.id, min_qty=max(mn, 5), max_qty=max(round(dem * (lt + 18)), 20), multiple=6 if info["cost"] < 20 else 1))
        if info["demand"] >= 4:
            for st in (st1, st2):
                db.add(ReorderRule(product_id=p.id, site_id=st.id, source_site_id=wh.id, min_qty=round(info["demand"] * 6), max_qty=round(info["demand"] * 12), multiple=1))

    # an open cycle count on the Haifa back room with one variance entered
    back = db.scalar(select(Location).where(Location.site_id == st2.id, Location.code == "BACK"))
    floor_root = site_root(db, st2.id)
    cc = CycleCount(number=next_number(db, CycleCount, "CC"), location_id=floor_root.id)
    db.add(cc)
    d.snapshot_count(db, cc)
    if cc.lines:
        cc.lines[0].counted = max(cc.lines[0].expected - 2, 0)
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
        print("seeded:", db.scalar(select(StockMove.id).order_by(StockMove.id.desc()).limit(1)), "ledger rows")
        print("logins: admin@stockpilot.dev/admin123 · manager@stockpilot.dev/manager123 · clerk@stockpilot.dev/clerk123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
