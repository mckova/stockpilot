"""Demo mode: a rule-based stand-in for Claude, used when no ANTHROPIC_API_KEY is set.

It plugs into the same agent loop as the real model, so everything below the
model is the real thing: the tools run against the live database, proposals land
in the same sign-off queue, and approval creates the same draft documents. What
is *not* real is the reasoning: intent is picked by keyword, and the wording is
templated. The UI says so. Set ANTHROPIC_API_KEY to use Claude instead.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, timedelta
from types import SimpleNamespace as NS
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Partner, POStatus, Product, PurchaseOrder

DEMO_MODEL = "demo (rule-based)"
HEBREW = re.compile(r"[֐-׿]")
PREFIX = re.compile(r"^\[[^\]]*\]\s*")

SITE_WORDS = {2: ("tel aviv", "tlv", "תל אביב", "תל-אביב"), 3: ("haifa", "hfa", "חיפה")}

HELP_EN = (
    "I'm running in demo mode, so I answer a fixed set of questions from your live data:\n\n"
    "- What needs attention today / run the morning review\n"
    "- What should we reorder, and from whom\n"
    "- Which short-dated lots are at risk\n"
    "- Are any reorder rules out of line with the forecast\n"
    "- What is the stock position at Tel Aviv or Haifa\n\n"
    "Set `ANTHROPIC_API_KEY` on the server to ask anything in your own words."
)
HELP_HE = (
    "אני בדמו, ולכן אני עונה על קבוצת שאלות קבועה מתוך הנתונים החיים:\n\n"
    "- מה דורש תשומת לב היום / סקירת בוקר\n"
    "- מה להזמין ומאיזה ספק\n"
    "- אילו אצוות עומדות לפוג\n"
    "- האם כללי ההזמנה מתאימים לתחזית\n"
    "- מה מצב המלאי בתל אביב או בחיפה\n\n"
    "כדי לשאול בחופשיות צריך להגדיר `ANTHROPIC_API_KEY` בשרת."
)


def _intent(text: str) -> tuple[str, int | None]:
    t = text.lower()
    site = next((sid for sid, words in SITE_WORDS.items() if any(w in t for w in words)), None)
    if "daily replenishment" in t or "morning review" in t:
        return "review", None
    if any(w in t for w in ("expir", "short-dated", "short dated", "תוקף", "פג ", "פגי", "אצוו")):
        return "expiry", None
    if any(w in t for w in ("rule", "forecast", "כלל", "כללי", "תחזית")):
        return "rules", None
    if site and any(w in t for w in ("stock", "inventory", "short", "missing", "מלאי", "חסר", "מצב")):
        return "site", site
    if any(w in t for w in ("reorder", "buy", "purchase", "supplier", "order", "הזמנ", "רכש", "ספק", "להזמין")):
        return "reorder", site
    if any(w in t for w in ("attention", "today", "review", "what needs", "תשומת", "היום", "סקירה")):
        return "review", None
    return "help", None


def _turn_state(messages: list[dict]) -> tuple[str, list[dict], dict[str, Any]]:
    """The current user text, the tool calls made so far this turn, and their parsed results."""
    start = max(i for i, m in enumerate(messages) if m["role"] == "user" and isinstance(m["content"], str))
    text = PREFIX.sub("", messages[start]["content"])
    calls: list[dict] = []
    results: dict[str, Any] = {}
    names: dict[str, str] = {}
    for m in messages[start + 1:]:
        if m["role"] == "assistant":
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    calls.append(b)
                    names[b["id"]] = b["name"]
        else:
            for b in m["content"]:
                if b.get("type") == "tool_result" and not b.get("is_error"):
                    try:
                        results[names[b["tool_use_id"]]] = json.loads(b["content"])
                    except (ValueError, KeyError):
                        pass
    return text, calls, results


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x - round(x)) < 0.05 else f"{x:,.1f}"


def _table(head: list[str], rows: list[list[str]]) -> str:
    return "| " + " | ".join(head) + " |\n|" + "---|" * len(head) + "\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows)


def _need(rep: list[dict]) -> list[dict]:
    return [r for r in rep if r["suggested_qty"] > 0]


def _plan_proposals(intent: str, site: int | None, results: dict[str, Any]) -> list[dict]:
    """The propose_* tool calls this question deserves, built from the read results."""
    rep = results.get("get_replenishment") or []
    ins = {r["product_id"]: r for r in (results.get("get_insights") or [])}
    calls: list[dict] = []
    if intent in ("review", "reorder", "site"):
        need = _need(rep)
        if site:
            need = [r for r in need if r["site_id"] == site]
        transfers: dict[tuple[int, int], list[dict]] = defaultdict(list)
        buys: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for r in need:
            if r["route"] == "transfer" and r["source_site_id"]:
                transfers[(r["source_site_id"], r["site_id"])].append(r)
            elif r["route"] == "buy" and r["supplier_id"]:
                buys[(r["supplier_id"], r["site_id"])].append(r)
        if intent != "site" or site:
            for (src, dst), rows in sorted(transfers.items()):
                calls.append({"name": "propose_transfer", "input": {
                    "from_site_id": src, "to_site_id": dst,
                    "lines": [{"product_id": r["product_id"], "qty": r["suggested_qty"]} for r in rows],
                    "rationale": f"{rows[0]['site']} is under its minimum on {len(rows)} product(s): "
                                 + ", ".join(f"{r['sku']} projected {_fmt(r['projected'])} vs min {_fmt(r['min_qty'])}" for r in rows[:3])
                                 + f". {rows[0]['source_site']} can cover it.",
                }})
        for (sup, dst), rows in sorted(buys.items()):
            calls.append({"name": "propose_purchase_order", "input": {
                "supplier_id": sup, "site_id": dst,
                "lines": [{"product_id": r["product_id"], "qty": r["suggested_qty"], "unit_cost": round(r["unit_cost"], 2)} for r in rows],
                "rationale": f"{rows[0]['site']} projected stock is under the minimum on {len(rows)} product(s) ordered from {rows[0]['supplier']}: "
                             + ", ".join(f"{r['sku']} {_fmt(r['projected'])} vs min {_fmt(r['min_qty'])}" for r in rows[:3]) + ".",
            }})
    if intent in ("rules", "review"):
        gaps = []
        for r in rep:
            rp = r.get("forecast_reorder_point") or 0
            if rp and (r["min_qty"] < 0.7 * rp or r["min_qty"] > 2.2 * rp):
                gaps.append((abs(r["min_qty"] - rp) / rp, r))
        if gaps:
            _, r = max(gaps, key=lambda g: g[0])
            rp = r["forecast_reorder_point"]
            calls.append({"name": "propose_reorder_rule", "input": {
                "product_id": r["product_id"], "site_id": r["site_id"], "min_qty": round(rp),
                "max_qty": round(max(rp * 2, r["max_qty"] if r["max_qty"] < rp * 2.5 else rp * 2)),
                "multiple": r["multiple"], "source_site_id": r["source_site_id"] or 0,
                "rationale": f"{r['sku']} at {r['site']}: the rule minimum is {_fmt(r['min_qty'])} but the forecast reorder point "
                             f"(lead-time demand plus safety stock) is {_fmt(rp)}.",
            }})
    return calls[:6]


def _compose(intent: str, site: int | None, he: bool, results: dict[str, Any], proposals: list[dict]) -> str:
    rep = results.get("get_replenishment") or []
    dash = results.get("get_dashboard") or {}
    ins = {r["product_id"]: r for r in (results.get("get_insights") or [])}
    sku_of = {r["product_id"]: r["sku"] for r in rep}
    out: list[str] = []
    need = _need(rep)
    if site:
        need = [r for r in need if r["site_id"] == site]

    if intent in ("review", "site", "reorder"):
        if need:
            where = need[0]["site"] if site else f"{len({r['site_id'] for r in need})} site(s)"
            if he:
                out.append(f"**{len(need)} פריטים מתחת למינימום ב-{where}.**")
            else:
                out.append(f"**{len(need)} product lines are under their minimum at {where}.**")
            rows = [[r["sku"], r["site"], _fmt(r["projected"]), _fmt(r["min_qty"]), _fmt(r["suggested_qty"]), ("קנייה" if he else "buy") if r["route"] == "buy" else ("העברה" if he else "move")] for r in need[:8]]
            head = ["מק\"ט", "אתר", "צפוי", "מינימום", "מוצע", "מסלול"] if he else ["SKU", "Site", "Projected", "Min", "Suggested", "Route"]
            out.append(_table(head, rows))
        else:
            out.append("הכול מעל המינימום." if he else "**Nothing is under its minimum.** Projected stock (on hand plus incoming) covers every rule.")
        exp = dash.get("expiring_lots") or []
        if intent == "review" and exp:
            top = exp[0]
            line = f"{sku_of.get(top['product_id'], top['product_id'])}, lot {top['lot']}: {_fmt(top['quantity'])} units expire in {top['days_left']} days"
            out.append((f"עוד דבר: {line}." if he else f"Also: {line}. {len(exp)} lots expire within 30 days in total."))
        if intent == "review" and dash:
            out.append(f"Stock value {_fmt(dash['stock_value'])}, {dash['open_purchase_orders']} open purchase orders, {dash['orders_to_ship']} order(s) to ship.")
    elif intent == "expiry":
        exp = dash.get("expiring_lots") or []
        if not exp:
            out.append("No lots expire in the next 30 days.")
        else:
            rows = []
            for e in exp[:8]:
                i = ins.get(e["product_id"], {})
                rows.append([sku_of.get(e["product_id"], str(e["product_id"])), e["lot"], str(e["days_left"]), _fmt(e["quantity"]), _fmt(i.get("avg_daily_demand", 0)),
                             "at risk" if i and i["avg_daily_demand"] * e["days_left"] < e["quantity"] else "will sell"])
            out.append(f"**{len(exp)} lots expire within 30 days.** Daily demand is the network forecast; a lot is at risk when it will not sell through before its date.")
            out.append(_table(["SKU", "Lot", "Days left", "Qty", "Demand/day", "Outlook"], rows))
            out.append("Plan: FEFO already picks the oldest lot first, so keep selling it first. For lots marked at risk, move them to the store that sells that product fastest, or mark them down this week.")
    elif intent == "rules":
        flagged = [r for r in rep if r.get("forecast_reorder_point") and (r["min_qty"] < 0.7 * r["forecast_reorder_point"] or r["min_qty"] > 2.2 * r["forecast_reorder_point"])]
        if not flagged:
            out.append("**No rule is far from its forecast.** Every minimum is within a reasonable band of the forecast reorder point.")
        else:
            rows = [[r["sku"], r["site"], _fmt(r["min_qty"]), _fmt(r["forecast_reorder_point"])] for r in flagged[:8]]
            out.append(f"**{len(flagged)} rule(s) are out of line with the demand forecast.**")
            out.append(_table(["SKU", "Site", "Rule min", "Forecast reorder point"], rows))

    if intent == "reorder" and not any(p["name"] == "propose_purchase_order" for p in proposals):
        out.append("אין צורך בהזמנת רכש מספק: המחסן המרכזי מעל המינימום והחנויות מתמלאות ממנו בהעברה." if he else
                   "No supplier order is needed: the warehouse is above its minimum, so the stores are refilled from it by transfer.")
    if proposals:
        kinds = {"propose_transfer": ("העברות", "transfer(s)"), "propose_purchase_order": ("הזמנות רכש", "purchase order(s)"), "propose_reorder_rule": ("שינויי כלל", "rule change(s)")}
        i = 0 if he else 1
        listed = ", ".join(f"{sum(1 for p in proposals if p['name'] == n)} {k[i]}" for n, k in kinds.items() if any(p["name"] == n for p in proposals))
        out.append((f"הצעתי {listed}. הן ממתינות לאישור מנהל בתור מימין, ושום דבר לא זז לפני כן." if he else f"I proposed {listed}. They wait for a manager's approval in the queue on the right; nothing moves until then."))
    elif intent in ("review", "site", "rules"):
        out.append("אין מה להציע כרגע." if he else "There is nothing to propose right now.")
    out.append("Demo mode: rule-based answers over your live data.")
    return "\n\n".join(out)


class DemoMessages:
    """Quacks like ``anthropic.Anthropic().beta.messages`` for the two ways we use it."""

    is_demo = True

    def create(self, **kw: Any) -> Any:
        usage = NS(input_tokens=0, output_tokens=0)

        def reply(stop: str, content: list[dict]) -> Any:
            return NS(stop_reason=stop, model=DEMO_MODEL, usage=usage, content=content)

        text, calls, results = _turn_state(kw["messages"])
        intent, site = _intent(text)
        he = bool(HEBREW.search(text))
        if intent == "help":
            return reply("end_turn", [{"type": "text", "text": HELP_HE if he else HELP_EN}])

        def use(name: str, args: dict) -> dict:
            return {"type": "tool_use", "id": f"demo_{len(calls) + 1}_{name}", "name": name, "input": args}

        if not results:  # round 1: read the data
            reads = [use("get_replenishment", {}), use("get_dashboard", {}), use("get_insights", {"site_id": 0})]
            return reply("tool_use", reads)
        proposed = [c for c in calls if c["name"].startswith("propose_")]
        if not proposed:
            plan = _plan_proposals(intent, site, results)
            if plan:  # round 2: propose
                return reply("tool_use", [use(p["name"], p["input"]) for p in plan])
        return reply("end_turn", [{"type": "text", "text": _compose(intent, site, he, results, proposed)}])


def sample_extraction(db: Session) -> dict[str, Any]:
    """A plausible delivery note for the first open purchase order, with realistic differences.

    Demo mode cannot read a photo. It builds a note from the open PO (with one short
    delivery, one price change and a damage note) so the receiving flow can be tried.
    """
    pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_([POStatus.confirmed, POStatus.partial])).order_by(PurchaseOrder.id.desc())))
    if not pos:
        return {"supplier_name": "", "document_number": "", "document_date": date.today().isoformat(), "lines": [], "notes": "Demo mode: no open purchase order to build a sample note from."}
    po = pos[0]
    supplier = db.get(Partner, po.supplier_id).name
    lines = []
    for i, pl in enumerate(po.lines):
        open_qty = pl.qty_ordered - pl.qty_received
        if open_qty <= 0:
            continue
        product: Product = pl.product
        lot = f"D{date.today():%y%m}-{100 + pl.id}" if product.tracking.value == "lot" else ""
        expiry = (date.today() + timedelta(days=120)).isoformat() if lot else ""
        lines.append({
            "description": product.name, "sku": product.sku if i % 2 == 0 else "",
            "quantity": round(open_qty * (0.9 if i == 1 else 1), 2),
            "unit_cost": round(pl.unit_cost * (1.06 if i == 0 else 1), 2),
            "lot_code": lot, "expiry_date": expiry,
        })
    return {
        "supplier_name": supplier, "document_number": f"DN-{7000 + po.id}", "document_date": date.today().isoformat(),
        "lines": lines, "notes": "Demo mode: this sample note was generated from the open order, not read from your file.",
    }
