import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as dbmod
from app.auth import hash_password
from app.main import app
from app.models import Base, Partner, Product, Role, Site, SiteKind, Tracking, User
from app.services.stock import site_root


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


@pytest.fixture()
def world(session):
    """Two sites, a supplier, a customer, a plain and a lot-tracked product, three users."""
    db = session
    users = {
        r: User(email=f"{r.value}@t.dev", name=r.value, role=r, password_hash=hash_password("pw"))
        for r in Role
    }
    db.add_all(users.values())
    wh = Site(code="WH", name="Warehouse", kind=SiteKind.warehouse)
    st = Site(code="ST", name="Store", kind=SiteKind.store)
    db.add_all([wh, st])
    sup = Partner(name="Supplier", kind="supplier", lead_time_days=2)
    cust = Partner(name="Customer", kind="customer")
    db.add_all([sup, cust])
    db.flush()
    plain = Product(sku="MUG", name="Mug", avg_cost=0, sale_price=10, preferred_supplier_id=sup.id)
    milk = Product(sku="MILK", name="Milk", tracking=Tracking.lot, sale_price=5, preferred_supplier_id=sup.id)
    db.add_all([plain, milk])
    site_root(db, wh.id)
    site_root(db, st.id)
    db.commit()
    return {"db": db, "wh": wh, "st": st, "sup": sup, "cust": cust, "mug": plain, "milk": milk, "users": users}


@pytest.fixture()
def client(world):
    def override():
        yield world["db"]

    app.dependency_overrides[dbmod.get_db] = override
    c = TestClient(app)

    def login(role: Role):
        r = c.post("/api/auth/login", json={"email": f"{role.value}@t.dev", "password": "pw"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    c.headers_for = login
    yield c
    app.dependency_overrides.clear()
