"""Idempotent development seed resolved entirely through natural keys."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from .database import SessionLocal
from .models import Cena, Izdelek, RetailerProduct, Trgovina
from .taxonomy import classify_products, sync_taxonomy


PRODUCTS = [
    ("Mleko Pomurske mlekarne 1,5%", "mlečni izdelki", "1L", Decimal("1.49")),
    ("Mleko Pomurske mlekarne 3,5%", "mlečni izdelki", "1L", Decimal("1.59")),
    ("Mleko Alpsko 1,5%", "mlečni izdelki", "1L", Decimal("1.65")),
    ("Mleko Alpsko 3,5%", "mlečni izdelki", "1L", Decimal("1.69")),
    ("Kruh Drožnik Žito", "pekovski izdelki", "400g", Decimal("1.40")),
]


def seed_session(db):
    taxonomy_categories = sync_taxonomy(db)
    today = date.today()
    product_ids = set()
    stores = {}
    for name in ("SPAR", "Mercator"):
        store = db.scalar(select(Trgovina).where(Trgovina.ime == name))
        if store is None:
            store = Trgovina(ime=name)
            db.add(store)
            db.flush()
        stores[name] = store
    for name, category, unit, base_price in PRODUCTS:
        product = db.scalar(
            select(Izdelek).where(
                Izdelek.ime == name,
                Izdelek.kategorija == category,
                Izdelek.enota == unit,
            )
        )
        if product is None:
            product = Izdelek(ime=name, kategorija=category, enota=unit)
            db.add(product)
            db.flush()
        product_ids.add(product.id)
        for store_name, store in stores.items():
            external_id = f"seed:{product.id}"
            retailer_product = db.scalar(
                select(RetailerProduct).where(
                    RetailerProduct.trgovina_id == store.id,
                    RetailerProduct.external_id == external_id,
                )
            )
            if retailer_product is None:
                retailer_product = RetailerProduct(
                    trgovina_id=store.id,
                    external_id=external_id,
                    ime=product.ime,
                    izdelek_id=product.id,
                    is_active=True,
                )
                db.add(retailer_product)
            else:
                retailer_product.ime = product.ime
                retailer_product.izdelek_id = product.id
                retailer_product.is_active = True
            price = base_price if store_name == "SPAR" else base_price + Decimal("0.10")
            row = db.scalar(
                select(Cena).where(
                    Cena.izdelek_id == product.id,
                    Cena.trgovina_id == store.id,
                    Cena.datum_zajema == today,
                )
            )
            if row is None:
                db.add(
                    Cena(
                        izdelek_id=product.id,
                        trgovina_id=store.id,
                        datum_zajema=today,
                        cena=price,
                    )
                )
            else:
                row.cena = price
    classify_products(db, product_ids, categories_by_slug=taxonomy_categories)


def seed():
    with SessionLocal.begin() as db:
        seed_session(db)


if __name__ == "__main__":
    seed()
    print("Seed data is current")
