"""Tools the Stockpilot copilot can call.

Two kinds:

* **Read tools** run immediately and return JSON. They reuse exactly the same
  services as the REST API, so the agent sees the numbers the UI shows.
* **Proposal tools** never change stock. They store an ``AIProposal`` that a
  human approves or rejects in the UI; approval runs the normal service
  (create draft PO, draft transfer, reorder rule). The model is told this, so
  it plans with the approval step in mind.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import schemas as s
from ..models import (
    AIProposal,
    Partner,
    POLine,
    Product,
    PurchaseOrder,
    Quant,
    ReorderRule,
    SalesOrder,
    Site,
    SOStatus,
    StockMove,
    Transfer,
    TransferLine,
    User,
    utcnow,
)
from ..services import insights
from ..services.stock import StockError, availability, next_number


def _strict(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


INT = {"type": "integer"}
STR = {"type": "string"}
NUM = {"type": "number"}

TOOLS: list[dict] = [
    _strict("get_dashboard", "Network-wide KPIs: stock value, open orders, reorder alerts, lots expiring within 30 days, 30-day inbound/outbound value.", {}, []),
    _strict(
        "search_products",
        "Find products by name, SKU or barcode fragment. Returns id, SKU, name, tracking, cost, price and network on-hand/available/incoming.",
        {"query": STR}, ["query"],
    ),
    _strict(
        "get_product",
        "Everything about one product: availability per site (on hand, reserved, available, incoming, projected), quants by location and lot with expiry, forecast and the last 15 ledger moves.",
        {"product_id": INT}, ["product_id"],
    ),
    _strict(
        "get_insights",
        "Per-product analytics: ABC class, forecast daily demand and sigma, safety stock, reorder point, days of cover, stockout date, dead-stock and risk flags. site_id 0 = whole network.",
        {"site_id": INT}, ["site_id"],
    ),
    _strict("get_replenishment", "Min/max reorder rules and what they currently suggest (route buy = purchase from supplier, transfer = from another site).", {}, []),
    _strict("list_sites_and_suppliers", "Sites (warehouse, stores) and suppliers with lead times. Use for ids before proposing documents.", {}, []),
    _strict(
        "list_open_orders",
        "Open purchase orders (draft/confirmed/partial) and sales orders waiting to ship, with lines.",
        {}, [],
    ),
    _strict(
        "get_ledger",
        "Ledger rows (append-only stock moves). Filter by product_id and/or reference such as PO-0012 (0 / empty string = no filter). Newest first.",
        {"product_id": INT, "reference": STR, "limit": INT}, ["product_id", "reference", "limit"],
    ),
    _strict(
        "propose_purchase_order",
        "Propose a purchase order. Nothing is ordered until a manager approves it in the UI; approval creates a DRAFT PO. Explain the reasoning in `rationale`.",
        {
            "supplier_id": INT,
            "site_id": INT,
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"product_id": INT, "qty": NUM, "unit_cost": NUM},
                    "required": ["product_id", "qty", "unit_cost"],
                    "additionalProperties": False,
                },
            },
            "rationale": STR,
        },
        ["supplier_id", "site_id", "lines", "rationale"],
    ),
    _strict(
        "propose_transfer",
        "Propose moving stock between two sites (e.g. warehouse to a store, or rebalancing short-dated lots to the store that sells them faster). Approval creates a DRAFT transfer.",
        {
            "from_site_id": INT,
            "to_site_id": INT,
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"product_id": INT, "qty": NUM},
                    "required": ["product_id", "qty"],
                    "additionalProperties": False,
                },
            },
            "rationale": STR,
        },
        ["from_site_id", "to_site_id", "lines", "rationale"],
    ),
    _strict(
        "propose_reorder_rule",
        "Propose creating or changing a min/max reorder rule (e.g. aligning min with the forecast reorder point). source_site_id 0 = buy from supplier.",
        {"product_id": INT, "site_id": INT, "min_qty": NUM, "max_qty": NUM, "multiple": NUM, "source_site_id": INT, "rationale": STR},
        ["product_id", "site_id", "min_qty", "max_qty", "multiple", "source_site_id", "rationale"],
    ),
]

PROPOSAL_TOOLS = {"propose_purchase_order", "propose_transfer", "propose_reorder_rule"}


# --------------------------------------------------------------------------- read tools

def _get_dashboard(db: Session, _: dict) -> dict:
    d = insights.dashboard(db)
    d["movement_30d"] = d["movement_30d"][-10:]  # keep the context lean
    return d


def _search_products(db: Session, args: dict) -> list[dict]:
    like = f"%{args['query']}%"
    rows = db.scalars(
        select(Product).where(or_(Product.sku.ilike(like), Product.name.ilike(like), Product.barcode.ilike(like))).limit(20)
    ).all()
    totals: dict[int, dict] = {}
    for r in availability(db):
        t = totals.setdefault(r["product_id"], {"on_hand": 0.0, "available": 0.0, "incoming": 0.0})
        for k in t:
            t[k] = round(t[k] + r[k], 3)
    keep = ("id", "sku", "name", "category", "tracking", "avg_cost", "sale_price", "preferred_supplier", "preferred_supplier_id")
    return [{**{k: s.product_out(p)[k] for k in keep}, **totals.get(p.id, {})} for p in rows]


def _get_product(db: Session, args: dict) -> dict:
    p = db.get(Product, args["product_id"])
    if p is None:
        raise StockError(f"product {args['product_id']} not found")
    sites = {x.id: x.name for x in db.scalars(select(Site))}
    ins = next((i for i in insights.product_insights(db) if i["product_id"] == p.id), None)
    if ins:
        ins = {k: v for k, v in ins.items() if k != "history_90d"}
        ins["last_14_days_shipped"] = next(i for i in insights.product_insights(db) if i["product_id"] == p.id)["history_90d"][-14:]
    moves = db.scalars(select(StockMove).where(StockMove.product_id == p.id).order_by(StockMove.id.desc()).limit(15)).all()
    return {
        "product": s.product_out(p),
        "availability": [{**a, "site": sites.get(a["site_id"])} for a in availability(db, product_id=p.id)],
        "quants": [
            {k: q[k] for k in ("location", "lot", "expiry_date", "quantity", "reserved", "available")}
            for q in map(s.quant_out, db.scalars(select(Quant).where(Quant.product_id == p.id)))
        ],
        "forecast": ins,
        "recent_moves": [
            {k: m[k] for k in ("created_at", "reference", "lot", "quantity", "from", "to", "reason")} for m in map(s.move_out, moves)
        ],
    }


def _get_insights(db: Session, args: dict) -> list[dict]:
    rows = insights.product_insights(db, site_id=args["site_id"] or None)
    return [{k: v for k, v in r.items() if k not in ("history_90d", "forecast_14d")} for r in rows]


def _get_replenishment(db: Session, _: dict) -> list[dict]:
    return insights.replenishment(db)


def _list_sites_and_suppliers(db: Session, _: dict) -> dict:
    return {
        "sites": [s.site_out(x) for x in db.scalars(select(Site))],
        "suppliers": [s.partner_out(x) for x in db.scalars(select(Partner).where(Partner.kind == "supplier"))],
    }


def _list_open_orders(db: Session, _: dict) -> dict:
    pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(["draft", "confirmed", "partial"]))).all()
    sos = db.scalars(select(SalesOrder).where(SalesOrder.status.in_([SOStatus.draft, SOStatus.reserved]))).all()
    return {"purchase_orders": [s.po_out(p) for p in pos], "sales_orders": [s.so_out(x) for x in sos]}


def _get_ledger(db: Session, args: dict) -> list[dict]:
    stmt = select(StockMove).order_by(StockMove.id.desc()).limit(max(1, min(args["limit"] or 30, 100)))
    if args["product_id"]:
        stmt = stmt.where(StockMove.product_id == args["product_id"])
    if args["reference"]:
        stmt = stmt.where(StockMove.reference == args["reference"])
    return [s.move_out(m) for m in db.scalars(stmt)]


# --------------------------------------------------------------------------- proposal tools

def _validate_lines(db: Session, lines: list[dict]) -> None:
    if not lines:
        raise StockError("a proposal needs at least one line")
    for line in lines:
        if db.get(Product, line["product_id"]) is None:
            raise StockError(f"product {line['product_id']} not found")
        if line["qty"] <= 0:
            raise StockError("quantities must be positive")


def _propose(db: Session, kind: str, args: dict, conversation_id: int | None) -> dict:
    payload = {k: v for k, v in args.items() if k != "rationale"}
    if kind == "purchase_order":
        sup = db.get(Partner, args["supplier_id"])
        if sup is None or sup.kind != "supplier":
            raise StockError(f"supplier {args['supplier_id']} not found")
        if db.get(Site, args["site_id"]) is None:
            raise StockError(f"site {args['site_id']} not found")
        _validate_lines(db, args["lines"])
    elif kind == "transfer":
        if args["from_site_id"] == args["to_site_id"]:
            raise StockError("a transfer needs two different sites")
        _validate_lines(db, args["lines"])
    elif kind == "reorder_rule":
        if args["max_qty"] < args["min_qty"]:
            raise StockError("max_qty must be >= min_qty")
        if db.get(Product, args["product_id"]) is None or db.get(Site, args["site_id"]) is None:
            raise StockError("unknown product or site")
    # Asking twice must not queue the same change twice: reuse an identical pending proposal.
    dumped = json.dumps(payload)
    same = db.scalar(select(AIProposal).where(AIProposal.kind == kind, AIProposal.status == "pending", AIProposal.payload == dumped))
    if same is not None:
        return {"proposal_id": same.id, "status": "pending_human_approval", "note": "An identical proposal is already waiting for approval."}
    prop = AIProposal(kind=kind, payload=dumped, rationale=args.get("rationale", ""), conversation_id=conversation_id)
    db.add(prop)
    db.flush()
    return {"proposal_id": prop.id, "status": "pending_human_approval", "note": "Shown to the user with Approve/Reject buttons. Do not claim it is done."}


def execute_tool(db: Session, name: str, args: dict, conversation_id: int | None = None):
    readers = {
        "get_dashboard": _get_dashboard,
        "search_products": _search_products,
        "get_product": _get_product,
        "get_insights": _get_insights,
        "get_replenishment": _get_replenishment,
        "list_sites_and_suppliers": _list_sites_and_suppliers,
        "list_open_orders": _list_open_orders,
        "get_ledger": _get_ledger,
    }
    if name in readers:
        return readers[name](db, args)
    if name in PROPOSAL_TOOLS:
        return _propose(db, name.removeprefix("propose_"), args, conversation_id)
    raise StockError(f"unknown tool {name}")


# --------------------------------------------------------------------------- approval

def approve_proposal(db: Session, prop: AIProposal, user: User) -> dict:
    """Turn an approved proposal into a real (draft) document via the normal models."""
    if prop.status != "pending":
        raise StockError(f"proposal {prop.id} is already {prop.status}")
    data = json.loads(prop.payload)
    if prop.kind == "purchase_order":
        sup = db.get(Partner, data["supplier_id"])
        po = PurchaseOrder(
            number=next_number(db, PurchaseOrder, "PO"), supplier_id=sup.id, site_id=data["site_id"],
            expected_date=(utcnow() + timedelta(days=sup.lead_time_days)).date(), note=f"AI copilot: {prop.rationale}"[:300],
        )
        po.lines = [POLine(product_id=x["product_id"], qty_ordered=x["qty"], unit_cost=x["unit_cost"]) for x in data["lines"]]
        db.add(po)
        db.flush()
        prop.result_ref = po.number
    elif prop.kind == "transfer":
        t = Transfer(number=next_number(db, Transfer, "TR"), from_site_id=data["from_site_id"], to_site_id=data["to_site_id"])
        t.lines = [TransferLine(product_id=x["product_id"], qty=x["qty"]) for x in data["lines"]]
        db.add(t)
        db.flush()
        prop.result_ref = t.number
    elif prop.kind == "reorder_rule":
        src = data["source_site_id"] or None
        r = db.scalar(select(ReorderRule).where(ReorderRule.product_id == data["product_id"], ReorderRule.site_id == data["site_id"]))
        if r is None:
            r = ReorderRule(product_id=data["product_id"], site_id=data["site_id"], min_qty=0, max_qty=0)
            db.add(r)
        r.min_qty, r.max_qty, r.multiple, r.source_site_id = data["min_qty"], data["max_qty"], data["multiple"] or 1, src
        db.flush()
        prop.result_ref = f"rule #{r.id}"
    prop.status = "approved"
    prop.decided_by = user.id
    return proposal_out(db, prop)


def proposal_out(db: Session, p: AIProposal) -> dict:
    data = json.loads(p.payload)
    names = {x.id: (x.sku, x.name) for x in db.scalars(select(Product))}
    sites = {x.id: x.name for x in db.scalars(select(Site))}
    lines = [{**x, "sku": names.get(x["product_id"], ("?",))[0], "product": names.get(x["product_id"], ("?", "?"))[1]} for x in data.get("lines", [])]
    summary = {
        "purchase_order": lambda: f"Buy from {getattr(db.get(Partner, data['supplier_id']), 'name', '?')} into {sites.get(data['site_id'])}",
        "transfer": lambda: f"Move {sites.get(data['from_site_id'])} → {sites.get(data['to_site_id'])}",
        "reorder_rule": lambda: f"{names.get(data['product_id'], ('?', '?'))[1]} @ {sites.get(data['site_id'])}: min {data['min_qty']} / max {data['max_qty']}",
    }[p.kind]()
    return {
        "id": p.id, "kind": p.kind, "status": p.status, "summary": summary, "rationale": p.rationale,
        "lines": lines, "payload": data, "result_ref": p.result_ref, "created_at": p.created_at.isoformat(),
    }

