"""Domain model.

* Locations are a tree, and *virtual* locations (supplier, customer,
  adjustment, transit) make every stock change a move between two
  locations: double-entry inventory.
* ``StockMove`` is an append-only ledger.
* ``Quant`` is the materialised on-hand per (product, location, lot), with a
  ``reserved`` column.
* Lots carry expiry dates so picking can be FEFO.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Text,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    clerk = "clerk"


class SiteKind(str, enum.Enum):
    warehouse = "warehouse"
    store = "store"


class LocationKind(str, enum.Enum):
    internal = "internal"      # physical bins/shelves: quantities are tracked
    supplier = "supplier"      # virtual source of purchases
    customer = "customer"      # virtual sink of sales
    adjustment = "adjustment"  # virtual counterpart of count gains/losses
    transit = "transit"        # virtual, between sites


class Tracking(str, enum.Enum):
    none = "none"
    lot = "lot"


class POStatus(str, enum.Enum):
    draft = "draft"
    confirmed = "confirmed"
    partial = "partial"
    received = "received"
    cancelled = "cancelled"


class SOStatus(str, enum.Enum):
    draft = "draft"
    reserved = "reserved"
    shipped = "shipped"
    cancelled = "cancelled"


class TransferStatus(str, enum.Enum):
    draft = "draft"
    in_transit = "in_transit"
    done = "done"
    cancelled = "cancelled"


class CountStatus(str, enum.Enum):
    open = "open"
    applied = "applied"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.clerk)
    password_hash: Mapped[str] = mapped_column(String(200))


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[SiteKind] = mapped_column(Enum(SiteKind))
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    locations: Mapped[list[Location]] = relationship(back_populates="site")


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[LocationKind] = mapped_column(Enum(LocationKind), default=LocationKind.internal)
    site: Mapped[Site | None] = relationship(back_populates="locations")
    parent: Mapped[Location | None] = relationship(remote_side="Location.id")

    @property
    def full_code(self) -> str:
        parts, node = [], self
        while node is not None:
            parts.append(node.code)
            node = node.parent
        return "/".join(reversed(parts))


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Partner(Base):
    __tablename__ = "partners"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # supplier | customer
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=3)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    barcode: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    uom: Mapped[str] = mapped_column(String(12), default="unit")
    tracking: Mapped[Tracking] = mapped_column(Enum(Tracking), default=Tracking.none)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)  # moving average (AVCO)
    sale_price: Mapped[float] = mapped_column(Float, default=0.0)
    preferred_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    category: Mapped[Category | None] = relationship()
    preferred_supplier: Mapped[Partner | None] = relationship()


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("product_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    code: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class Quant(Base):
    __tablename__ = "quants"
    __table_args__ = (UniqueConstraint("product_id", "location_id", "lot_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    reserved: Mapped[float] = mapped_column(Float, default=0.0)
    in_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    product: Mapped[Product] = relationship()
    location: Mapped[Location] = relationship()
    lot: Mapped[Lot | None] = relationship()

    @property
    def available(self) -> float:
        return round(self.quantity - self.reserved, 6)


class StockMove(Base):
    """Immutable ledger row. Never updated or deleted after insert."""

    __tablename__ = "stock_moves"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), nullable=True)
    quantity: Mapped[float] = mapped_column(Float)
    from_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    reference: Mapped[str] = mapped_column(String(60))  # e.g. PO-0003, SO-0012, CC-0001
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    product: Mapped[Product] = relationship()
    lot: Mapped[Lot | None] = relationship()
    from_location: Mapped[Location] = relationship(foreign_keys=[from_location_id])
    to_location: Mapped[Location] = relationship(foreign_keys=[to_location_id])
    user: Mapped[User | None] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("partners.id"))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    status: Mapped[POStatus] = mapped_column(Enum(POStatus), default=POStatus.draft)
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supplier: Mapped[Partner] = relationship()
    site: Mapped[Site] = relationship()
    lines: Mapped[list[POLine]] = relationship(cascade="all, delete-orphan", back_populates="order")


class POLine(Base):
    __tablename__ = "po_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty_ordered: Mapped[float] = mapped_column(Float)
    qty_received: Mapped[float] = mapped_column(Float, default=0.0)
    unit_cost: Mapped[float] = mapped_column(Float)
    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("partners.id"))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    status: Mapped[SOStatus] = mapped_column(Enum(SOStatus), default=SOStatus.draft)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    customer: Mapped[Partner] = relationship()
    site: Mapped[Site] = relationship()
    lines: Mapped[list[SOLine]] = relationship(cascade="all, delete-orphan", back_populates="order")


class SOLine(Base):
    __tablename__ = "so_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    order: Mapped[SalesOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()
    reservations: Mapped[list[Reservation]] = relationship(cascade="all, delete-orphan")


class Reservation(Base):
    """Which quant a sales line has claimed, so shipping picks exactly that stock."""

    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    so_line_id: Mapped[int] = mapped_column(ForeignKey("so_lines.id"))
    quant_id: Mapped[int] = mapped_column(ForeignKey("quants.id"))
    qty: Mapped[float] = mapped_column(Float)
    quant: Mapped[Quant] = relationship()


class Transfer(Base):
    __tablename__ = "transfers"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    from_site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    to_site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    status: Mapped[TransferStatus] = mapped_column(Enum(TransferStatus), default=TransferStatus.draft)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    from_site: Mapped[Site] = relationship(foreign_keys=[from_site_id])
    to_site: Mapped[Site] = relationship(foreign_keys=[to_site_id])
    lines: Mapped[list[TransferLine]] = relationship(cascade="all, delete-orphan")


class TransferLine(Base):
    __tablename__ = "transfer_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("transfers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[float] = mapped_column(Float)
    product: Mapped[Product] = relationship()


class CycleCount(Base):
    __tablename__ = "cycle_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[CountStatus] = mapped_column(Enum(CountStatus), default=CountStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    location: Mapped[Location] = relationship()
    lines: Mapped[list[CountLine]] = relationship(cascade="all, delete-orphan")


class CountLine(Base):
    __tablename__ = "count_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("cycle_counts.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), nullable=True)
    expected: Mapped[float] = mapped_column(Float)
    counted: Mapped[float | None] = mapped_column(Float, nullable=True)
    product: Mapped[Product] = relationship()
    lot: Mapped[Lot | None] = relationship()


class ReorderRule(Base):
    __tablename__ = "reorder_rules"
    __table_args__ = (UniqueConstraint("product_id", "site_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    min_qty: Mapped[float] = mapped_column(Float)
    max_qty: Mapped[float] = mapped_column(Float)
    multiple: Mapped[float] = mapped_column(Float, default=1.0)
    # route: None = buy from the preferred supplier; a site id = transfer from that site
    source_site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    product: Mapped[Product] = relationship()
    site: Mapped[Site] = relationship(foreign_keys=[site_id])
    source_site: Mapped[Site | None] = relationship(foreign_keys=[source_site_id])


class AIConversation(Base):
    """Copilot conversation. ``messages`` is the exact, append-only API transcript
    (JSON), so thinking blocks are replayed unchanged on every turn."""

    __tablename__ = "ai_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    messages: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class AIProposal(Base):
    """An action the copilot suggested. Nothing happens until a human approves."""

    __tablename__ = "ai_proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("ai_conversations.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # purchase_order | transfer | reorder_rule
    payload: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    result_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
