"""Request bodies and response serialisers."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from . import models as m


# --------------------------------------------------------------------------- inputs

class LoginIn(BaseModel):
    email: str
    password: str


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1)
    barcode: str | None = None
    category_id: int | None = None
    uom: str = "unit"
    tracking: m.Tracking = m.Tracking.none
    sale_price: float = Field(0, ge=0)
    avg_cost: float = Field(0, ge=0)
    preferred_supplier_id: int | None = None


class LocationIn(BaseModel):
    site_id: int
    parent_id: int | None = None
    code: str
    name: str


class PartnerIn(BaseModel):
    name: str
    kind: str = Field(pattern="^(supplier|customer)$")
    email: str | None = None
    lead_time_days: int = Field(3, ge=0)


class POLineIn(BaseModel):
    product_id: int
    qty_ordered: float = Field(gt=0)
    unit_cost: float = Field(ge=0)


class POIn(BaseModel):
    supplier_id: int
    site_id: int
    expected_date: date | None = None
    note: str | None = None
    lines: list[POLineIn]


class ReceiptIn(BaseModel):
    line_id: int
    qty: float = Field(gt=0)
    lot_code: str | None = None
    expiry_date: date | None = None
    location_id: int | None = None


class SOLineIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)
    unit_price: float | None = Field(None, ge=0)


class SOIn(BaseModel):
    customer_id: int
    site_id: int
    lines: list[SOLineIn]


class TransferLineIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)


class TransferIn(BaseModel):
    from_site_id: int
    to_site_id: int
    lines: list[TransferLineIn]


class CountIn(BaseModel):
    location_id: int


class CountEntry(BaseModel):
    line_id: int
    counted: float = Field(ge=0)


class RuleIn(BaseModel):
    product_id: int
    site_id: int
    min_qty: float = Field(ge=0)
    max_qty: float = Field(gt=0)
    multiple: float = Field(1, gt=0)
    source_site_id: int | None = None


class InternalMoveIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)
    from_location_id: int
    to_location_id: int
    lot_id: int | None = None


class GeneratePOIn(BaseModel):
    rule_ids: list[int] | None = None  # None = every rule that needs replenishment


# --------------------------------------------------------------------------- outputs

def user_out(u: m.User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role.value}


def site_out(s: m.Site) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "kind": s.kind.value, "city": s.city}


def location_out(loc: m.Location) -> dict:
    return {
        "id": loc.id, "site_id": loc.site_id, "parent_id": loc.parent_id, "code": loc.code,
        "full_code": loc.full_code, "name": loc.name, "kind": loc.kind.value,
    }


def product_out(p: m.Product) -> dict:
    return {
        "id": p.id, "sku": p.sku, "barcode": p.barcode, "name": p.name,
        "category_id": p.category_id, "category": p.category.name if p.category else None,
        "uom": p.uom, "tracking": p.tracking.value, "avg_cost": round(p.avg_cost, 4),
        "sale_price": p.sale_price, "preferred_supplier_id": p.preferred_supplier_id,
        "preferred_supplier": p.preferred_supplier.name if p.preferred_supplier else None,
        "active": p.active,
    }


def partner_out(p: m.Partner) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "email": p.email, "lead_time_days": p.lead_time_days}


def quant_out(q: m.Quant) -> dict:
    return {
        "id": q.id, "product_id": q.product_id, "sku": q.product.sku, "product": q.product.name,
        "location_id": q.location_id, "location": q.location.full_code, "site_id": q.location.site_id,
        "lot_id": q.lot_id, "lot": q.lot.code if q.lot else None,
        "expiry_date": q.lot.expiry_date.isoformat() if q.lot and q.lot.expiry_date else None,
        "quantity": q.quantity, "reserved": q.reserved, "available": q.available,
        "in_date": q.in_date.isoformat(), "value": round(q.quantity * q.product.avg_cost, 2),
    }


def move_out(mv: m.StockMove) -> dict:
    return {
        "id": mv.id, "created_at": mv.created_at.isoformat(), "product_id": mv.product_id,
        "sku": mv.product.sku, "product": mv.product.name, "lot": mv.lot.code if mv.lot else None,
        "quantity": mv.quantity, "from": mv.from_location.full_code, "to": mv.to_location.full_code,
        "from_kind": mv.from_location.kind.value, "to_kind": mv.to_location.kind.value,
        "unit_cost": mv.unit_cost, "reference": mv.reference, "reason": mv.reason,
        "user": mv.user.name if mv.user else None,
    }


def po_out(po: m.PurchaseOrder) -> dict:
    return {
        "id": po.id, "number": po.number, "status": po.status.value,
        "supplier_id": po.supplier_id, "supplier": po.supplier.name,
        "site_id": po.site_id, "site": po.site.name,
        "expected_date": po.expected_date.isoformat() if po.expected_date else None,
        "created_at": po.created_at.isoformat(), "note": po.note,
        "total": round(sum(line.qty_ordered * line.unit_cost for line in po.lines), 2),
        "lines": [
            {
                "id": line.id, "product_id": line.product_id, "sku": line.product.sku,
                "product": line.product.name, "tracking": line.product.tracking.value,
                "qty_ordered": line.qty_ordered, "qty_received": line.qty_received,
                "unit_cost": line.unit_cost,
            }
            for line in po.lines
        ],
    }


def so_out(so: m.SalesOrder) -> dict:
    return {
        "id": so.id, "number": so.number, "status": so.status.value,
        "customer_id": so.customer_id, "customer": so.customer.name,
        "site_id": so.site_id, "site": so.site.name, "created_at": so.created_at.isoformat(),
        "total": round(sum(line.qty * line.unit_price for line in so.lines), 2),
        "lines": [
            {
                "id": line.id, "product_id": line.product_id, "sku": line.product.sku,
                "product": line.product.name, "qty": line.qty, "unit_price": line.unit_price,
                "reserved": round(sum(r.qty for r in line.reservations), 3),
                "picks": [
                    {"location": r.quant.location.full_code, "lot": r.quant.lot.code if r.quant.lot else None, "qty": r.qty}
                    for r in line.reservations
                ],
            }
            for line in so.lines
        ],
    }


def transfer_out(t: m.Transfer) -> dict:
    return {
        "id": t.id, "number": t.number, "status": t.status.value,
        "from_site_id": t.from_site_id, "from_site": t.from_site.name,
        "to_site_id": t.to_site_id, "to_site": t.to_site.name, "created_at": t.created_at.isoformat(),
        "lines": [{"id": line.id, "product_id": line.product_id, "sku": line.product.sku, "product": line.product.name, "qty": line.qty} for line in t.lines],
    }


def count_out(c: m.CycleCount) -> dict:
    return {
        "id": c.id, "number": c.number, "status": c.status.value, "location_id": c.location_id,
        "location": c.location.full_code, "created_at": c.created_at.isoformat(),
        "lines": [
            {
                "id": line.id, "product_id": line.product_id, "sku": line.product.sku, "product": line.product.name,
                "lot": line.lot.code if line.lot else None, "expected": line.expected, "counted": line.counted,
                "variance": None if line.counted is None else round(line.counted - line.expected, 3),
                "variance_value": None if line.counted is None else round((line.counted - line.expected) * line.product.avg_cost, 2),
            }
            for line in c.lines
        ],
    }


def rule_out(r: m.ReorderRule) -> dict:
    return {
        "id": r.id, "product_id": r.product_id, "sku": r.product.sku, "product": r.product.name,
        "site_id": r.site_id, "site": r.site.name, "min_qty": r.min_qty, "max_qty": r.max_qty, "multiple": r.multiple,
        "source_site_id": r.source_site_id, "source_site": r.source_site.name if r.source_site else None,
        "route": "transfer" if r.source_site_id else "buy",
    }
