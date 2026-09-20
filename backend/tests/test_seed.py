from sqlalchemy import func, select

from backend.models import Category, Cena, Izdelek, RetailerProduct, Trgovina
from backend.seed import PRODUCTS, seed_session


def test_seed_is_idempotent_and_reuses_accented_products(db):
    seed_session(db)
    db.commit()
    seed_session(db)
    db.commit()

    assert db.scalar(select(func.count()).select_from(Izdelek)) == len(PRODUCTS)
    assert db.scalar(select(func.count()).select_from(Trgovina)) == 2
    assert db.scalar(select(func.count()).select_from(Cena)) == len(PRODUCTS) * 2
    assert db.scalar(select(func.count()).select_from(RetailerProduct)) == len(PRODUCTS) * 2
    assert set(db.scalars(select(RetailerProduct.is_active))) == {True}
    assert db.scalar(select(func.count()).select_from(Category)) > 0
    assert None not in set(db.scalars(select(Izdelek.category_id)))
    names = set(db.scalars(select(Izdelek.ime)))
    categories = set(db.scalars(select(Izdelek.kategorija)))
    assert "Kruh Drožnik Žito" in names
    assert "mlečni izdelki" in categories


def test_seeded_products_are_visible_in_catalog(client, db):
    seed_session(db)
    db.commit()

    response = client.get("/izdelki", params={"limit": 100})

    assert response.status_code == 200
    assert response.json()["total"] == len(PRODUCTS)
