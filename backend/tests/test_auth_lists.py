from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend import auth
from backend.config import get_settings
from backend.database import get_db
from backend.main import app
from backend.models import Izdelek, Seznam, SeznamIzdelek, User
from backend.tests.conftest import register


def test_auth_normalizes_email_hashes_password_and_returns_identity(client, db):
    headers = register(client, "Person@Example.COM")
    user = db.scalar(select(User))
    assert user.email == "person@example.com"
    assert user.password_hash != "correct-horse-battery"
    assert user.password_hash.startswith("$argon2")

    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "person@example.com"
    assert client.get("/auth/me").status_code == 401

    duplicate = client.post(
        "/auth/register",
        json={"email": "PERSON@example.com", "password": "another-long-password"},
    )
    assert duplicate.status_code == 409
    login = client.post(
        "/auth/login",
        json={"email": " PERSON@example.com ", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    assert client.post(
        "/auth/login", json={"email": "person@example.com", "password": "wrong"}
    ).status_code == 401


def test_lists_are_atomic_owner_scoped_and_reject_duplicates(client, db, catalog):
    _, _, first, second = catalog
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    payload = {
        "ime": "Weekly",
        "items": [
            {"izdelek_id": first.id, "kolicina": 2},
            {"izdelek_id": second.id, "kolicina": 3},
        ],
    }
    created = client.post("/seznami", json=payload, headers=alice)
    assert created.status_code == 201
    list_id = created.json()["id"]
    assert [item["izdelek_id"] for item in created.json()["izdelki"]] == [first.id, second.id]
    assert client.get(f"/seznami/{list_id}", headers=bob).status_code == 404
    assert client.post(
        f"/seznami/{list_id}/izdelki",
        json={"izdelek_id": first.id, "kolicina": 1},
        headers=bob,
    ).status_code == 404
    assert client.get("/seznami", headers=bob).json() == []
    assert len(client.get("/seznami", headers=alice).json()) == 1

    duplicate_add = client.post(
        f"/seznami/{list_id}/izdelki",
        json={"izdelek_id": first.id, "kolicina": 1},
        headers=alice,
    )
    assert duplicate_add.status_code == 409
    assert db.scalar(select(func.count()).select_from(SeznamIzdelek)) == 2


def test_invalid_list_payload_rolls_back_and_session_remains_usable(client, db, catalog):
    _, _, first, _ = catalog
    headers = register(client)
    before = db.scalar(select(func.count()).select_from(Seznam))
    unknown = client.post(
        "/seznami",
        json={"ime": "Bad", "items": [{"izdelek_id": 999999, "kolicina": 1}]},
        headers=headers,
    )
    assert unknown.status_code == 404
    assert db.scalar(select(func.count()).select_from(Seznam)) == before

    duplicate = client.post(
        "/seznami",
        json={
            "ime": "Duplicate",
            "items": [
                {"izdelek_id": first.id, "kolicina": 1},
                {"izdelek_id": first.id, "kolicina": 2},
            ],
        },
        headers=headers,
    )
    assert duplicate.status_code == 422
    assert db.scalar(select(func.count()).select_from(Seznam)) == before
    good = client.post(
        "/seznami",
        json={"ime": "Good", "items": [{"izdelek_id": first.id, "kolicina": 1}]},
        headers=headers,
    )
    assert good.status_code == 201


def test_quantity_and_request_bounds(client, catalog):
    _, _, first, _ = catalog
    assert client.post(
        "/primerjava", json={"items": [{"izdelek_id": first.id, "kolicina": 0}]}
    ).status_code == 422
    assert client.post("/primerjava", json={"items": []}).status_code == 422
    headers = register(client)
    assert client.post(
        "/seznami",
        json={"ime": "", "items": [{"izdelek_id": first.id, "kolicina": 1}]},
        headers=headers,
    ).status_code == 422


def test_health_and_readiness(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_readiness_rejects_missing_schema(client):
    empty_engine = create_engine("sqlite://")

    def empty_db():
        with Session(empty_engine) as session:
            yield session

    app.dependency_overrides[get_db] = empty_db
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database schema is not ready"


def test_login_uses_dummy_verification_for_unknown_users(monkeypatch):
    calls = []

    class FakePasswordHash:
        def verify(self, password, encoded):
            calls.append((password, encoded))
            return False

    monkeypatch.setattr(auth, "password_hash", FakePasswordHash())

    assert auth.verify_login_password(None, "wrong") is False
    assert calls == [("wrong", auth.dummy_password_hash)]


def test_auth_rate_limits_login_and_registration(client):
    settings = get_settings()
    original_login = settings.login_rate_limit
    original_register = settings.register_rate_limit
    try:
        settings.login_rate_limit = 2
        settings.register_rate_limit = 1
        for _ in range(2):
            assert client.post(
                "/auth/login",
                json={"email": "missing@example.com", "password": "wrong"},
            ).status_code == 401
        limited_login = client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "wrong"},
        )
        assert limited_login.status_code == 429
        assert limited_login.headers["retry-after"]

        assert client.post(
            "/auth/register",
            json={"email": "first@example.com", "password": "correct-horse-battery"},
        ).status_code == 201
        assert client.post(
            "/auth/register",
            json={"email": "second@example.com", "password": "correct-horse-battery"},
        ).status_code == 429
    finally:
        settings.login_rate_limit = original_login
        settings.register_rate_limit = original_register
        auth.auth_rate_limiter.clear()


def test_shopping_list_cannot_grow_beyond_item_limit(client, db):
    products = [Izdelek(ime=f"Product {index}") for index in range(101)]
    db.add_all(products)
    db.commit()
    headers = register(client, "bounded@example.com")
    created = client.post(
        "/seznami",
        json={
            "ime": "Full",
            "items": [
                {"izdelek_id": product.id, "kolicina": 1}
                for product in products[:100]
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    response = client.post(
        f"/seznami/{created.json()['id']}/izdelki",
        json={"izdelek_id": products[100].id, "kolicina": 1},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Shopping list item limit reached"
