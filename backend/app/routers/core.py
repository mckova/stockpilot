"""Auth, master data (sites, locations, partners, products) and stock queries."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import schemas as s
from ..auth import current_user, make_token, require, verify_password
from ..db import get_db
from ..models import (
    Category,
    Location,
    LocationKind,
    Lot,
    Partner,
    Product,
    Quant,
    Role,
    Site,
    StockMove,
    User,
)
from ..services.stock import apply_move, availability, subtree_ids

router = APIRouter(prefix="/api")


def _get(db: Session, model, oid: int):
    obj = db.get(model, oid)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {oid} not found")
    return obj


# --------------------------------------------------------------------------- auth

@router.post("/auth/login")
def login(body: s.LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "wrong email or password")
    return {"token": make_token(user), "user": s.user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return s.user_out(user)


# --------------------------------------------------------------------------- master data

@router.get("/sites")
def list_sites(db: Session = Depends(get_db), _=Depends(current_user)):
    return [s.site_out(x) for x in db.scalars(select(Site).order_by(Site.id))]


@router.get("/locations")
def list_locations(site_id: int | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    stmt = select(Location).order_by(Location.site_id, Location.id)
    if site_id:
        stmt = stmt.where(Location.site_id == site_id)
    return [s.location_out(x) for x in db.scalars(stmt)]


@router.post("/locations", status_code=201)
def create_location(body: s.LocationIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    _get(db, Site, body.site_id)
    if body.parent_id:
        parent = _get(db, Location, body.parent_id)
        if parent.site_id != body.site_id:
            raise HTTPException(422, "parent location belongs to another site")
    loc = Location(site_id=body.site_id, parent_id=body.parent_id, code=body.code, name=body.name, kind=LocationKind.internal)
    db.add(loc)
    db.commit()
    return s.location_out(loc)


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _=Depends(current_user)):
    return [{"id": c.id, "name": c.name} for c in db.scalars(select(Category).order_by(Category.name))]


@router.get("/partners")
def list_partners(kind: str | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    stmt = select(Partner).order_by(Partner.name)
    if kind:
        stmt = stmt.where(Partner.kind == kind)
    return [s.partner_out(p) for p in db.scalars(stmt)]


@router.post("/partners", status_code=201)
def create_partner(body: s.PartnerIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    p = Partner(**body.model_dump())
    db.add(p)
    db.commit()
    return s.partner_out(p)


@router.get("/products")
def list_products(q: str | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    stmt = select(Product).order_by(Product.sku)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.sku.ilike(like), Product.name.ilike(like), Product.barcode == q))
    products = db.scalars(stmt).all()
    totals: dict[int, dict] = {}
    for row in availability(db):
        t = totals.setdefault(row["product_id"], {"on_hand": 0.0, "available": 0.0, "incoming": 0.0})
        for k in t:
            t[k] += row[k]
    return [{**s.product_out(p), **totals.get(p.id, {"on_hand": 0, "available": 0, "incoming": 0})} for p in products]


@router.get("/products/barcode/{code}")
def product_by_barcode(code: str, db: Session = Depends(get_db), _=Depends(current_user)):
    p = db.scalar(select(Product).where(or_(Product.barcode == code, Product.sku == code)))
    if p is None:
        raise HTTPException(404, f"no product with barcode or SKU '{code}'")
    return s.product_out(p)


@router.get("/products/{pid}")
def get_product(pid: int, db: Session = Depends(get_db), _=Depends(current_user)):
    p = _get(db, Product, pid)
    quants = db.scalars(select(Quant).where(Quant.product_id == pid)).all()
    moves = db.scalars(
        select(StockMove).where(StockMove.product_id == pid).order_by(StockMove.id.desc()).limit(50)
    ).all()
    lots = db.scalars(select(Lot).where(Lot.product_id == pid).order_by(Lot.expiry_date)).all()
    return {
        **s.product_out(p),
        "availability": availability(db, product_id=pid),
        "quants": [s.quant_out(q) for q in quants],
        "lots": [{"id": lot.id, "code": lot.code, "expiry_date": lot.expiry_date.isoformat() if lot.expiry_date else None} for lot in lots],
        "moves": [s.move_out(mv) for mv in moves],
    }


@router.post("/products", status_code=201)
def create_product(body: s.ProductIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    if db.scalar(select(Product).where(Product.sku == body.sku)):
        raise HTTPException(409, f"SKU {body.sku} already exists")
    p = Product(**body.model_dump())
    db.add(p)
    db.commit()
    return s.product_out(p)


@router.put("/products/{pid}")
def update_product(pid: int, body: s.ProductIn, db: Session = Depends(get_db), _=Depends(require(Role.manager))):
    p = _get(db, Product, pid)
    data = body.model_dump()
    data.pop("avg_cost")  # valuation is owned by the ledger, never edited by hand
    if data["tracking"] != p.tracking and db.scalar(select(Quant.id).where(Quant.product_id == pid)):
        raise HTTPException(409, "cannot change tracking while the product has stock")
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return s.product_out(p)


# --------------------------------------------------------------------------- stock

@router.get("/stock/availability")
def get_availability(site_id: int | None = None, product_id: int | None = None, db: Session = Depends(get_db), _=Depends(current_user)):
    return availability(db, product_id=product_id, site_id=site_id)


@router.get("/stock/quants")
def list_quants(
    site_id: int | None = None,
    location_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(current_user),
):
    stmt = select(Quant).join(Location)
    if site_id:
        stmt = stmt.where(Location.site_id == site_id)
    if location_id:
        stmt = stmt.where(Quant.location_id.in_(subtree_ids(db, location_id)))
    if product_id:
        stmt = stmt.where(Quant.product_id == product_id)
    return [s.quant_out(q) for q in db.scalars(stmt.order_by(Quant.product_id, Location.id))]


@router.get("/stock/moves")
def list_moves(
    product_id: int | None = None,
    reference: str | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
    _=Depends(current_user),
):
    stmt = select(StockMove).order_by(StockMove.id.desc()).limit(limit)
    if product_id:
        stmt = stmt.where(StockMove.product_id == product_id)
    if reference:
        stmt = stmt.where(StockMove.reference == reference)
    return [s.move_out(mv) for mv in db.scalars(stmt)]


@router.post("/stock/move", status_code=201)
def internal_move(body: s.InternalMoveIn, db: Session = Depends(get_db), user: User = Depends(require(Role.clerk))):
    """Put-away / re-slotting between two bins of the same site."""
    src, dst = _get(db, Location, body.from_location_id), _get(db, Location, body.to_location_id)
    if src.kind != LocationKind.internal or dst.kind != LocationKind.internal or src.site_id != dst.site_id:
        raise HTTPException(422, "internal moves are between bins of one site; use a transfer between sites")
    product = _get(db, Product, body.product_id)
    lot = _get(db, Lot, body.lot_id) if body.lot_id else None
    mv = apply_move(db, product=product, qty=body.qty, src=src, dst=dst, lot=lot, reference="INT", reason="internal move", user=user)
    db.commit()
    return s.move_out(mv)
