"""End-to-end flows through the HTTP API, including auth and roles."""
from app.models import Role


def test_requires_auth(client):
    assert client.get("/api/products").status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@t.dev", "password": "nope"}).status_code == 401


def test_clerk_cannot_buy_but_can_sell(client, world):
    clerk = client.headers_for(Role.clerk)
    body = {"supplier_id": world["sup"].id, "site_id": world["wh"].id, "lines": [{"product_id": world["mug"].id, "qty_ordered": 5, "unit_cost": 1}]}
    assert client.post("/api/purchase-orders", json=body, headers=clerk).status_code == 403
    so = {"customer_id": world["cust"].id, "site_id": world["wh"].id, "lines": [{"product_id": world["mug"].id, "qty": 1}]}
    r = client.post("/api/sales-orders", json=so, headers=clerk)
    assert r.status_code == 201 and r.json()["lines"][0]["unit_price"] == 10  # defaults to sale price


def test_purchase_to_delivery_flow(client, world):
    mgr = client.headers_for(Role.manager)
    po = client.post("/api/purchase-orders", headers=mgr, json={
        "supplier_id": world["sup"].id, "site_id": world["wh"].id,
        "lines": [{"product_id": world["mug"].id, "qty_ordered": 20, "unit_cost": 3}],
    }).json()
    assert client.post(f"/api/purchase-orders/{po['id']}/confirm", headers=mgr).json()["status"] == "confirmed"
    avail = client.get("/api/stock/availability", headers=mgr).json()
    assert avail[0]["incoming"] == 20 and avail[0]["projected"] == 20

    r = client.post(f"/api/purchase-orders/{po['id']}/receive", headers=mgr, json=[{"line_id": po["lines"][0]["id"], "qty": 20}])
    assert r.json()["status"] == "received"

    so = client.post("/api/sales-orders", headers=mgr, json={
        "customer_id": world["cust"].id, "site_id": world["wh"].id, "lines": [{"product_id": world["mug"].id, "qty": 25}],
    }).json()
    r = client.post(f"/api/sales-orders/{so['id']}/reserve", headers=mgr)
    assert r.status_code == 409 and "insufficient" in r.json()["detail"]

    so = client.post("/api/sales-orders", headers=mgr, json={
        "customer_id": world["cust"].id, "site_id": world["wh"].id, "lines": [{"product_id": world["mug"].id, "qty": 8}],
    }).json()
    assert client.post(f"/api/sales-orders/{so['id']}/reserve", headers=mgr).json()["status"] == "reserved"
    assert client.post(f"/api/sales-orders/{so['id']}/ship", headers=mgr).json()["status"] == "shipped"

    moves = client.get("/api/stock/moves", headers=mgr).json()
    assert [(m["reference"], m["quantity"]) for m in moves][:2] == [(so["number"], 8), (po["number"], 20)]
    product = client.get(f"/api/products/{world['mug'].id}", headers=mgr).json()
    assert product["availability"][0]["on_hand"] == 12 and product["avg_cost"] == 3


def test_replenishment_generates_po_and_transfer(client, world):
    mgr = client.headers_for(Role.manager)
    client.post("/api/reorder-rules", headers=mgr, json={"product_id": world["mug"].id, "site_id": world["wh"].id, "min_qty": 10, "max_qty": 50, "multiple": 12})
    client.post("/api/reorder-rules", headers=mgr, json={"product_id": world["mug"].id, "site_id": world["st"].id, "min_qty": 2, "max_qty": 6, "source_site_id": world["wh"].id})
    sugg = {r["site_id"]: r for r in client.get("/api/replenishment", headers=mgr).json()}
    assert sugg[world["wh"].id]["suggested_qty"] == 60  # 50 rounded up to a multiple of 12
    assert sugg[world["st"].id]["route"] == "transfer" and sugg[world["st"].id]["suggested_qty"] == 6

    out = client.post("/api/replenishment/generate", headers=mgr, json={}).json()
    assert len(out["purchase_orders"]) == 1 and out["purchase_orders"][0]["lines"][0]["qty_ordered"] == 60
    assert len(out["transfers"]) == 1 and out["transfers"][0]["lines"][0]["qty"] == 6
    # the drafts count as incoming, so the rules are satisfied and nothing is suggested twice
    assert all(r["suggested_qty"] == 0 for r in client.get("/api/replenishment", headers=mgr).json())


def test_count_flow_and_dashboard(client, world):
    mgr = client.headers_for(Role.manager)
    po = client.post("/api/purchase-orders", headers=mgr, json={
        "supplier_id": world["sup"].id, "site_id": world["wh"].id,
        "lines": [{"product_id": world["mug"].id, "qty_ordered": 10, "unit_cost": 2}],
    }).json()
    client.post(f"/api/purchase-orders/{po['id']}/confirm", headers=mgr)
    client.post(f"/api/purchase-orders/{po['id']}/receive", headers=mgr, json=[{"line_id": po["lines"][0]["id"], "qty": 10}])
    root = [loc for loc in client.get("/api/locations", headers=mgr).json() if loc["site_id"] == world["wh"].id][0]
    cc = client.post("/api/counts", headers=mgr, json={"location_id": root["id"]}).json()
    cc = client.put(f"/api/counts/{cc['id']}", headers=mgr, json=[{"line_id": cc["lines"][0]["id"], "counted": 12}]).json()
    assert cc["lines"][0]["variance"] == 2 and cc["lines"][0]["variance_value"] == 4
    clerk = client.headers_for(Role.clerk)
    assert client.post(f"/api/counts/{cc['id']}/apply", headers=clerk).status_code == 403  # approval is a manager's job
    assert client.post(f"/api/counts/{cc['id']}/apply", headers=mgr).json()["status"] == "applied"
    dash = client.get("/api/dashboard", headers=mgr).json()
    assert dash["units_on_hand"] == 12 and dash["stock_value"] == 24
    assert len(dash["movement_30d"]) == 30


def test_pos_checkout_sells_from_the_store_only(client, world):
    from app.models import Transfer, TransferLine
    from app.services import documents as d
    mgr = client.headers_for(Role.manager)
    po = client.post("/api/purchase-orders", headers=mgr, json={
        "supplier_id": world["sup"].id, "site_id": world["wh"].id,
        "lines": [{"product_id": world["mug"].id, "qty_ordered": 10, "unit_cost": 2}],
    }).json()
    client.post(f"/api/purchase-orders/{po['id']}/confirm", headers=mgr)
    client.post(f"/api/purchase-orders/{po['id']}/receive", headers=mgr, json=[{"line_id": po["lines"][0]["id"], "qty": 10}])
    clerk = client.headers_for(Role.clerk)
    cart = {"site_id": world["st"].id, "lines": [{"product_id": world["mug"].id, "qty": 1}]}
    r = client.post("/api/pos/checkout", headers=clerk, json=cart)
    assert r.status_code == 409  # the store has none: warehouse stock is not sold at the counter

    db = world["db"]
    tr = Transfer(number="TR-1", from_site_id=world["wh"].id, to_site_id=world["st"].id)
    tr.lines.append(TransferLine(product_id=world["mug"].id, product=world["mug"], qty=4))
    db.add(tr)
    db.flush()
    d.dispatch_transfer(db, tr, None)
    d.receive_transfer(db, tr, None)
    db.commit()

    cart["lines"] = [{"product_id": world["mug"].id, "qty": 1}, {"product_id": world["mug"].id, "qty": 2}]
    sale = client.post("/api/pos/checkout", headers=clerk, json=cart).json()
    assert sale["status"] == "shipped" and sale["customer"] == "Walk-in (Store)"
    assert sale["lines"][0]["qty"] == 3 and sale["total"] == 30
    dash = client.get(f"/api/dashboard?site_id={world['st'].id}", headers=mgr).json()
    assert dash["units_on_hand"] == 1
    network = client.get("/api/dashboard", headers=mgr).json()
    assert network["units_on_hand"] == 7 and {s["name"] for s in network["sites"]} == {"Warehouse", "Store"}
