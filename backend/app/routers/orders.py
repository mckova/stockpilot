"""Purchase orders, sales orders and inter-site transfers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas as s
from ..auth import current_user, require
from ..db import get_db
from ..models import (
    Partner,
    POLine,
    Product,
    PurchaseOrder,
    Role,
    SalesOrder,
    Site,
    SOLine,
    Transfer,
    TransferLine,
    User,
)
from ..services import documents as d
from ..services.stock import next_number

router = APIRouter(prefix="/api")


def _get(db: Session, model, oid: int):
    obj = db.get(model, oid)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {oid} not found")
    return obj


def _partner(db: Session, pid: int, kind: str) -> Partner:
    p = _get(db, Partner, pid)
    if p.kind != kind:
        raise HTTPException(422, f"partner {p.name} is not a {kind}")
    return p


# --------------------------------------------------------------------------- purchase orders

@router.get("/purchase-orders")
def list_pos(status: str | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    return [s.po_out(po) for po in db.scalars(stmt)]


@router.get("/purchase-orders/{oid}")
def get_po(oid: int, db: Session = Depends(get_db), _=Depends(current_user)):
    return s.po_out(_get(db, PurchaseOrder, oid))


@router.post("/purchase-orders", status_code=201)
def create_po(body: s.POIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    _partner(db, body.supplier_id, "supplier")
    _get(db, Site, body.site_id)
    po = PurchaseOrder(
        number=next_number(db, PurchaseOrder, "PO"), supplier_id=body.supplier_id, site_id=body.site_id,
        expected_date=body.expected_date, note=body.note,
    )
    for line in body.lines:
        _get(db, Product, line.product_id)
        po.lines.append(POLine(**line.model_dump()))
    db.add(po)
    db.commit()
    return s.po_out(po)


@router.post("/purchase-orders/{oid}/confirm")
def confirm_po(oid: int, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    po = d.confirm_po(db, _get(db, PurchaseOrder, oid))
    db.commit()
    return s.po_out(po)


@router.post("/purchase-orders/{oid}/receive")
def receive_po(oid: int, body: list[s.ReceiptIn], db: Session = Depends(get_db), user: User = Depends(require(Role.clerk))):
    po = _get(db, PurchaseOrder, oid)
    d.receive_po(db, po, [r.model_dump() for r in body], user)
    db.commit()
    return s.po_out(po)


@router.post("/purchase-orders/{oid}/cancel")
def cancel_po(oid: int, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    po = d.cancel_po(db, _get(db, PurchaseOrder, oid))
    db.commit()
    return s.po_out(po)


# --------------------------------------------------------------------------- sales orders

@router.get("/sales-orders")
def list_sos(status: str | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    stmt = select(SalesOrder).order_by(SalesOrder.id.desc())
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    return [s.so_out(so) for so in db.scalars(stmt)]


@router.post("/sales-orders", status_code=201)
def create_so(body: s.SOIn, db: Session = Depends(get_db), _=Depends(require(Role.clerk))):
    _partner(db, body.customer_id, "customer")
    _get(db, Site, body.site_id)
    so = SalesOrder(number=next_number(db, SalesOrder, "SO"), customer_id=body.customer_id, site_id=body.site_id)
    for line in body.lines:
        product = _get(db, Product, line.product_id)
        price = product.sale_price if line.unit_price is None else line.unit_price
        so.lines.append(SOLine(product_id=line.product_id, qty=line.qty, unit_price=price))
    db.add(so)
    db.commit()
    return s.so_out(so)


@router.post("/sales-orders/{oid}/reserve")
def reserve_so(oid: int, db: Session = Depends(get_db), _=Depends(require(Role.clerk))):
    so = d.reserve_so(db, _get(db, SalesOrder, oid))
    db.commit()
    return s.so_out(so)


@router.post("/sales-orders/{oid}/ship")
def ship_so(oid: int, db: Session = Depends(get_db), user: User = Depends(require(Role.clerk))):
    so = _get(db, SalesOrder, oid)
    d.ship_so(db, so, user)
    db.commit()
    return s.so_out(so)


@router.post("/sales-orders/{oid}/cancel")
def cancel_so(oid: int, db: Session = Depends(get_db), _=Depends(require(Role.clerk))):
    so = d.cancel_so(db, _get(db, SalesOrder, oid))
    db.commit()
    return s.so_out(so)


# --------------------------------------------------------------------------- transfers

@router.get("/transfers")
def list_transfers(db: Session = Depends(get_db), _=Depends(current_user)):
    return [s.transfer_out(t) for t in db.scalars(select(Transfer).order_by(Transfer.id.desc()))]


@router.post("/transfers", status_code=201)
def create_transfer(body: s.TransferIn, db: Session = Depends(get_db), _=Depends(require(Role.clerk))):
    if body.from_site_id == body.to_site_id:
        raise HTTPException(422, "a transfer needs two different sites")
    _get(db, Site, body.from_site_id)
    _get(db, Site, body.to_site_id)
    t = Transfer(number=next_number(db, Transfer, "TR"), from_site_id=body.from_site_id, to_site_id=body.to_site_id)
    for line in body.lines:
        _get(db, Product, line.product_id)
        t.lines.append(TransferLine(**line.model_dump()))
    db.add(t)
    db.commit()
    return s.transfer_out(t)


@router.post("/transfers/{oid}/dispatch")
def dispatch(oid: int, db: Session = Depends(get_db), user: User = Depends(require(Role.clerk))):
    t = _get(db, Transfer, oid)
    d.dispatch_transfer(db, t, user)
    db.commit()
    return s.transfer_out(t)


@router.post("/transfers/{oid}/receive")
def receive(oid: int, db: Session = Depends(get_db), user: User = Depends(require(Role.clerk))):
    t = _get(db, Transfer, oid)
    d.receive_transfer(db, t, user)
    db.commit()
    return s.transfer_out(t)
