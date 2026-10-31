"""AI goods-in: read a supplier delivery note or invoice (photo or PDF) and turn
it into a receipt the clerk only has to confirm.

Claude reads the document with vision and returns JSON constrained by a schema
(structured outputs), so parsing never fails. Matching the extracted lines to
the purchase order is done in plain code, so it is deterministic and testable.
"""
from __future__ import annotations

import base64
import difflib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Partner, POStatus, Product, PurchaseOrder
from ..services.stock import StockError
from .agent import EFFORT, FALLBACK_BETA, MODEL, MessagesClient

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_BYTES = 15 * 1024 * 1024

SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {"type": "string"},
        "document_number": {"type": "string"},
        "document_date": {"type": "string", "description": "ISO date, or empty"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "sku": {"type": "string", "description": "supplier or our SKU if printed, else empty"},
                    "quantity": {"type": "number"},
                    "unit_cost": {"type": "number", "description": "0 if not printed"},
                    "lot_code": {"type": "string", "description": "batch/lot if printed, else empty"},
                    "expiry_date": {"type": "string", "description": "ISO date (YYYY-MM-DD) if printed, else empty"},
                },
                "required": ["description", "sku", "quantity", "unit_cost", "lot_code", "expiry_date"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "damage, shortages or anything a receiver should know; empty if none"},
    },
    "required": ["supplier_name", "document_number", "document_date", "lines", "notes"],
    "additionalProperties": False,
}

PROMPT = """This is a supplier delivery note or invoice received at our warehouse.
Extract every product line exactly as printed: description, SKU/code, delivered quantity (units, not cases,
unless only cases are shown), unit cost, lot/batch and expiry date. Normalise dates to YYYY-MM-DD.
Do not invent values: use an empty string or 0 when a field is not on the document.
Our catalogue, to help you read codes and names (SKU | name):
{catalogue}"""


def _content_block(data: bytes, media_type: str) -> dict:
    b64 = base64.standard_b64encode(data).decode()
    if media_type == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    if media_type in IMAGE_TYPES:
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
    raise StockError(f"unsupported file type {media_type}: upload a PDF or an image")


def extract(db: Session, client: MessagesClient, data: bytes, media_type: str) -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise StockError("file is larger than 15 MB")
    catalogue = "\n".join(f"{p.sku} | {p.name}" for p in db.scalars(select(Product).where(Product.active.is_(True))))
    response = client.create(
        model=MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": [_content_block(data, media_type), {"type": "text", "text": PROMPT.format(catalogue=catalogue)}]}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise StockError("the document could not be processed")
    text = next((b.text if hasattr(b, "text") else b.get("text") for b in response.content
                 if (getattr(b, "type", None) or b.get("type")) == "text"), None)
    if not text:
        raise StockError("no data was extracted from the document")
    return json.loads(text)


def _match_product(line: dict, products: list[Product]) -> tuple[Product | None, float]:
    sku = (line.get("sku") or "").strip().upper()
    for p in products:
        if sku and (p.sku.upper() == sku or (p.barcode or "") == sku):
            return p, 1.0
    best, score = None, 0.0
    for p in products:
        desc, name = line["description"].lower(), p.name.lower()
        r = difflib.SequenceMatcher(None, desc, name).ratio()
        words = [w for w in name.split() if len(w) > 2]
        if words and all(w in desc for w in words):  # every word of our name is printed
            r = max(r, 0.85)
        if r > score:
            best, score = p, r
    return (best, round(score, 2)) if score >= 0.55 else (None, round(score, 2))


def match_to_po(db: Session, extraction: dict, po_id: int | None) -> dict[str, Any]:
    """Pick the PO (given, or the open PO of the matching supplier) and map lines onto it."""
    open_pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_([POStatus.confirmed, POStatus.partial]))))
    po = db.get(PurchaseOrder, po_id) if po_id else None
    if po is None and open_pos:
        names = {p.id: db.get(Partner, p.supplier_id).name.lower() for p in open_pos}
        ranked = sorted(open_pos, key=lambda p: -difflib.SequenceMatcher(None, extraction["supplier_name"].lower(), names[p.id]).ratio())
        po = ranked[0]
    products = list(db.scalars(select(Product)))
    receipts, unmatched, warnings = [], [], []
    if po is not None and extraction["supplier_name"]:
        po_supplier = db.get(Partner, po.supplier_id).name
        if difflib.SequenceMatcher(None, extraction["supplier_name"].lower(), po_supplier.lower()).ratio() < 0.6:
            better = [p for p in open_pos if p.id != po.id and difflib.SequenceMatcher(
                None, extraction["supplier_name"].lower(), db.get(Partner, p.supplier_id).name.lower()).ratio() >= 0.6]
            hint = f"; it looks like {better[0].number}" if better else ""
            warnings.append(f"Document is from {extraction['supplier_name']} but {po.number} is from {po_supplier}{hint}")
    for line in extraction["lines"]:
        product, confidence = _match_product(line, products)
        po_line = next((pl for pl in po.lines if product and pl.product_id == product.id), None) if po else None
        if po_line is None:
            unmatched.append({**line, "matched_sku": product.sku if product else None, "confidence": confidence})
            continue
        open_qty = po_line.qty_ordered - po_line.qty_received
        qty = min(line["quantity"], open_qty)
        if line["quantity"] > open_qty:
            warnings.append(f"{product.sku}: delivered {line['quantity']:g} but only {open_qty:g} open on {po.number}")
        if line["unit_cost"] and abs(line["unit_cost"] - po_line.unit_cost) > 0.01 * max(po_line.unit_cost, 1):
            warnings.append(f"{product.sku}: invoiced at {line['unit_cost']:g} vs {po_line.unit_cost:g} on the PO")
        if product.tracking.value == "lot" and not line["lot_code"]:
            warnings.append(f"{product.sku}: lot-tracked but no lot on the document, enter it before posting")
        receipts.append({
            "line_id": po_line.id, "sku": product.sku, "product": product.name, "qty": qty,
            "lot_code": line["lot_code"] or None, "expiry_date": line["expiry_date"] or None, "confidence": confidence,
        })
    for pl in po.lines if po else []:
        if not any(r["line_id"] == pl.id for r in receipts) and pl.qty_received < pl.qty_ordered:
            warnings.append(f"{pl.product.sku}: on {po.number} but not on the delivery note")
    if extraction.get("notes"):
        warnings.append(f"Note on document: {extraction['notes']}")
    return {
        "po_id": po.id if po else None, "po_number": po.number if po else None,
        "supplier": extraction["supplier_name"], "document_number": extraction["document_number"],
        "receipts": receipts, "unmatched": unmatched, "warnings": warnings,
    }
