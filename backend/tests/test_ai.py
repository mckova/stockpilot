"""The copilot loop with a scripted fake Claude client (no network, no key).

Checks the parts we own: request shape (model, strict tools, fallbacks, effort),
tool execution, one-message tool results, append-only transcript, and that
proposals change nothing until a manager approves them.
"""
import json
from types import SimpleNamespace as NS

from app.models import Role
from app.routers import ai as ai_router


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        stop, content = self.script.pop(0)
        return NS(stop_reason=stop, content=content, model=kw["model"], usage=NS(input_tokens=100, output_tokens=20))


def tool_use(id_, name, inp):
    return {"type": "tool_use", "id": id_, "name": name, "input": inp}


def text(t):
    return {"type": "text", "text": t}


def _use(client_app, fake):
    from app.main import app
    app.dependency_overrides[ai_router.get_client] = lambda: fake


def test_chat_runs_tools_and_creates_pending_proposal(client, world):
    mgr = client.headers_for(Role.manager)
    fake = FakeClient([
        ("tool_use", [{"type": "thinking", "thinking": "", "signature": "sig1"},
                      tool_use("t1", "search_products", {"query": "mug"}),
                      tool_use("t2", "get_replenishment", {})]),
        ("tool_use", [tool_use("t3", "propose_purchase_order", {
            "supplier_id": world["sup"].id, "site_id": world["wh"].id,
            "lines": [{"product_id": world["mug"].id, "qty": 24, "unit_cost": 3.5}], "rationale": "no mugs on hand"})]),
        ("end_turn", [text("You have no mugs. I proposed PO for 24, awaiting approval.")]),
    ])
    _use(client, fake)
    r = client.post("/api/ai/chat", headers=mgr, json={"message": "Do we need mugs?"}).json()

    assert r["text"].startswith("You have no mugs")
    assert [s["tool"] for s in r["steps"]] == ["search_products", "get_replenishment", "propose_purchase_order"]
    assert len(r["proposals"]) == 1 and r["proposals"][0]["status"] == "pending"

    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["output_config"]["effort"] and all(t["strict"] for t in first["tools"])
    # both tool results returned together, thinking block replayed unchanged
    second = fake.calls[1]["messages"]
    assert second[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig1"}
    assert [b["tool_use_id"] for b in second[2]["content"]] == ["t1", "t2"]

    # nothing was ordered yet
    assert client.get("/api/purchase-orders", headers=mgr).json() == []
    # a clerk cannot approve; a manager can, which creates a draft PO
    pid = r["proposals"][0]["id"]
    assert client.post(f"/api/ai/proposals/{pid}/approve", headers=client.headers_for(Role.clerk)).status_code == 403
    done = client.post(f"/api/ai/proposals/{pid}/approve", headers=mgr).json()
    assert done["status"] == "approved" and done["result_ref"].startswith("PO-")
    pos = client.get("/api/purchase-orders", headers=mgr).json()
    assert pos[0]["status"] == "draft" and pos[0]["lines"][0]["qty_ordered"] == 24
    assert client.post(f"/api/ai/proposals/{pid}/approve", headers=mgr).status_code == 409


def test_conversation_continues_and_tool_errors_are_reported(client, world):
    mgr = client.headers_for(Role.manager)
    fake = FakeClient([
        ("end_turn", [text("Hi!")]),
        ("tool_use", [tool_use("t1", "get_product", {"product_id": 999})]),
        ("end_turn", [text("That product does not exist.")]),
    ])
    _use(client, fake)
    c1 = client.post("/api/ai/chat", headers=mgr, json={"message": "hello"}).json()
    c2 = client.post("/api/ai/chat", headers=mgr, json={"message": "product 999?", "conversation_id": c1["conversation_id"]}).json()
    assert c2["conversation_id"] == c1["conversation_id"] and c2["steps"][0]["ok"] is False
    err = fake.calls[2]["messages"][-1]["content"][0]
    assert err["is_error"] is True and "not found" in err["content"]
    hist = client.get(f"/api/ai/conversations/{c1['conversation_id']}", headers=mgr).json()["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant", "user", "assistant"]


def test_refusal_and_missing_key(client, world, monkeypatch):
    mgr = client.headers_for(Role.manager)
    _use(client, FakeClient([("refusal", [])]))
    assert "can't help" in client.post("/api/ai/chat", headers=mgr, json={"message": "x"}).json()["text"]
    from app.main import app
    app.dependency_overrides.pop(ai_router.get_client)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert client.post("/api/ai/chat", headers=mgr, json={"message": "x"}).status_code == 503
    assert client.get("/api/ai/status", headers=mgr).json()["enabled"] is False


def test_intake_reads_delivery_note_and_matches_po(client, world):
    mgr = client.headers_for(Role.manager)
    po = client.post("/api/purchase-orders", headers=mgr, json={
        "supplier_id": world["sup"].id, "site_id": world["wh"].id,
        "lines": [{"product_id": world["mug"].id, "qty_ordered": 10, "unit_cost": 2},
                  {"product_id": world["milk"].id, "qty_ordered": 20, "unit_cost": 1}],
    }).json()
    client.post(f"/api/purchase-orders/{po['id']}/confirm", headers=mgr)
    extracted = {"supplier_name": "Supplier Ltd", "document_number": "DN-77", "document_date": "2026-10-30", "notes": "",
                 "lines": [{"description": "Mug", "sku": "MUG", "quantity": 12, "unit_cost": 2.5, "lot_code": "", "expiry_date": ""},
                           {"description": "Fresh milk 1L", "sku": "", "quantity": 20, "unit_cost": 1, "lot_code": "B7", "expiry_date": "2026-11-20"}]}
    fake = FakeClient([("end_turn", [text(json.dumps(extracted))])])
    _use(client, fake)
    r = client.post("/api/ai/intake/receipt", headers=client.headers_for(Role.clerk),
                    files={"file": ("note.png", b"\x89PNG fake", "image/png")}).json()
    call = fake.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["messages"][0]["content"][0]["type"] == "image"
    assert r["po_number"] == po["number"]
    by_sku = {x["sku"]: x for x in r["receipts"]}
    assert by_sku["MUG"]["qty"] == 10 and by_sku["MILK"]["lot_code"] == "B7"  # name-matched, capped at open qty
    assert any("delivered 12" in w for w in r["warnings"]) and any("2.5" in w for w in r["warnings"])
    # the clerk posts it as-is
    body = [{"line_id": x["line_id"], "qty": x["qty"], "lot_code": x["lot_code"], "expiry_date": x["expiry_date"]} for x in r["receipts"]]
    assert client.post(f"/api/purchase-orders/{po['id']}/receive", headers=mgr, json=body).json()["status"] == "received"


def test_planner_run_fills_the_queue(client, world):
    mgr = client.headers_for(Role.manager)
    fake = FakeClient([
        ("tool_use", [tool_use("t1", "propose_reorder_rule", {"product_id": world["mug"].id, "site_id": world["wh"].id,
                                                              "min_qty": 10, "max_qty": 40, "multiple": 1, "source_site_id": 0,
                                                              "rationale": "no rule yet"})]),
        ("end_turn", [text("Brief: added a rule for mugs.")]),
    ])
    _use(client, fake)
    r = client.post("/api/ai/planner/run", headers=mgr).json()
    assert r["proposals"][0]["kind"] == "reorder_rule" and "Brief" in r["text"]
    assert "daily replenishment" in fake.calls[0]["messages"][0]["content"]
    assert client.post("/api/ai/planner/run", headers=client.headers_for(Role.clerk)).status_code == 403


def test_intake_warns_when_the_note_is_from_another_supplier(client, world):
    mgr = client.headers_for(Role.manager)
    po = client.post("/api/purchase-orders", headers=mgr, json={
        "supplier_id": world["sup"].id, "site_id": world["wh"].id,
        "lines": [{"product_id": world["mug"].id, "qty_ordered": 5, "unit_cost": 2}]}).json()
    client.post(f"/api/purchase-orders/{po['id']}/confirm", headers=mgr)
    extracted = {"supplier_name": "Completely Different Trading", "document_number": "X1", "document_date": "", "notes": "",
                 "lines": [{"description": "Mug", "sku": "MUG", "quantity": 5, "unit_cost": 2, "lot_code": "", "expiry_date": ""}]}
    _use(client, FakeClient([("end_turn", [text(json.dumps(extracted))])]))
    r = client.post("/api/ai/intake/receipt", headers=mgr, data={"po_id": str(po["id"])},
                    files={"file": ("note.pdf", b"%PDF-1.4 fake", "application/pdf")}).json()
    assert any("Document is from Completely Different Trading" in w for w in r["warnings"])
