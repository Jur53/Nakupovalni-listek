from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from backend.models import Cena, Izdelek, RetailerProduct, Seznam, SeznamIzdelek, Trgovina, User
from backend.product_mappings import MappingMember, ProductMapping, apply_curated_mappings


def test_curated_mapping_merges_products_prices_and_saved_list_items(db):
    first_store = Trgovina(ime="Store One")
    second_store = Trgovina(ime="Store Two")
    first = Izdelek(ime="Retailer name one", kategorija="old", enota="1L")
    second = Izdelek(ime="Retailer name two", kategorija="old", enota="liter")
    user = User(email="mapping@example.com", password_hash="unused")
    db.add_all([first_store, second_store, first, second, user])
    db.flush()
    sources = [
        RetailerProduct(
            trgovina_id=first_store.id,
            external_id="one",
            ime=first.ime,
            izdelek_id=first.id,
        ),
        RetailerProduct(
            trgovina_id=second_store.id,
            external_id="two",
            ime=second.ime,
            izdelek_id=second.id,
        ),
    ]
    db.add_all(sources)
    shopping_list = Seznam(user_id=user.id, ime="Milk")
    shopping_list.izdelki = [
        SeznamIzdelek(izdelek_id=first.id, kolicina=1),
        SeznamIzdelek(izdelek_id=second.id, kolicina=2),
    ]
    db.add(shopping_list)
    db.add_all(
        [
            Cena(
                izdelek_id=first.id,
                trgovina_id=first_store.id,
                cena=Decimal("1.50"),
                datum_zajema=date(2026, 9, 19),
            ),
            Cena(
                izdelek_id=second.id,
                trgovina_id=second_store.id,
                cena=Decimal("1.60"),
                datum_zajema=date(2026, 9, 19),
            ),
        ]
    )
    db.flush()

    assignments = apply_curated_mappings(
        db,
        (
            ProductMapping(
                key="same-milk",
                name="One milk",
                category="Milk",
                unit="1 l",
                members=(
                    MappingMember(retailer="Store One", external_id="one"),
                    MappingMember(retailer="Store Two", external_id="two"),
                ),
            ),
        ),
    )
    db.flush()

    canonical_ids = set(db.scalars(select(RetailerProduct.izdelek_id)))
    assert len(canonical_ids) == 1
    canonical_id = canonical_ids.pop()
    assert assignments == {sources[0].id: canonical_id, sources[1].id: canonical_id}
    canonical = db.get(Izdelek, canonical_id)
    assert (canonical.ime, canonical.kategorija, canonical.enota) == ("One milk", "Milk", "1 l")
    assert db.scalar(select(func.count()).select_from(Izdelek)) == 1
    assert set(db.scalars(select(Cena.izdelek_id))) == {canonical_id}
    items = db.scalars(select(SeznamIzdelek)).all()
    assert len(items) == 1
    assert items[0].izdelek_id == canonical_id
    assert items[0].kolicina == 3
