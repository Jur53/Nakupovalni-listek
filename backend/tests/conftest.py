from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.auth import auth_rate_limiter
from backend.main import app
from backend.models import Cena, Izdelek, RetailerProduct, Trgovina


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def database():
    auth_rate_limiter.clear()
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        # SQLite applies RESTRICT while dropping a populated self-referential
        # table, so detach the taxonomy tree before the normal metadata cleanup.
        with engine.begin() as connection:
            connection.execute(text("UPDATE izdelki SET category_id = NULL"))
            connection.execute(text("UPDATE categories SET parent_id = NULL"))
        Base.metadata.drop_all(engine)
        auth_rate_limiter.clear()


@pytest.fixture
def db():
    with TestingSession() as session:
        yield session


@pytest.fixture
def client():
    def override_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def catalog(db):
    store_a = Trgovina(ime="Store A")
    store_b = Trgovina(ime="Store B")
    first = Izdelek(ime="Same name", kategorija="one", enota="kg")
    second = Izdelek(ime="Same name", kategorija="two", enota="piece")
    db.add_all([store_a, store_b, first, second])
    db.flush()
    db.add_all(
        [
            Cena(izdelek_id=first.id, trgovina_id=store_a.id, cena=Decimal("9.99"), datum_zajema=date(2025, 1, 1)),
            Cena(izdelek_id=first.id, trgovina_id=store_a.id, cena=Decimal("1.10"), datum_zajema=date(2025, 2, 1)),
            Cena(izdelek_id=second.id, trgovina_id=store_a.id, cena=Decimal("2.20"), datum_zajema=date(2025, 2, 1)),
            Cena(izdelek_id=first.id, trgovina_id=store_b.id, cena=Decimal("1.00"), datum_zajema=date(2025, 2, 1)),
            Cena(izdelek_id=second.id, trgovina_id=store_b.id, cena=Decimal("3.00"), datum_zajema=date(2025, 2, 1)),
        ]
    )
    db.add_all(
        [
            RetailerProduct(
                trgovina_id=store.id,
                external_id=f"{store.id}-{product.id}",
                ime=product.ime,
                izdelek_id=product.id,
                is_active=True,
            )
            for store in (store_a, store_b)
            for product in (first, second)
        ]
    )
    db.commit()
    return store_a, store_b, first, second


def register(client, email="user@example.com"):
    response = client.post("/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
