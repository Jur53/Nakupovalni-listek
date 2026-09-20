from datetime import date
from decimal import Decimal

from backend.models import Cena, Izdelek


def test_product_catalog_supports_search_category_and_pagination(client, catalog):
    response = client.get("/izdelki", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["categories"] == ["one", "two"]
    assert page["category_tree"] == []
    assert page["items"][0]["kategorija_id"] is None
    assert page["items"][0]["kategorija_pot"] == []
    assert page["items"][0]["najcenejsa_ponudba"] == {
        "trgovina_id": catalog[1].id,
        "ime_trgovina": "Store B",
        "cena": "1.00",
        "datum_zajema": "2025-02-01",
    }
    assert page["items"][0]["ponudbe"] == [
        {
            "trgovina_id": catalog[1].id,
            "ime_trgovina": "Store B",
            "cena": "1.00",
            "datum_zajema": "2025-02-01",
        },
        {
            "trgovina_id": catalog[0].id,
            "ime_trgovina": "Store A",
            "cena": "1.10",
            "datum_zajema": "2025-02-01",
        },
    ]

    filtered = client.get("/izdelki", params={"q": "same", "kategorija": "two"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["kategorija"] == "two"

    literal_wildcard = client.get("/izdelki", params={"q": "%"})
    assert literal_wildcard.status_code == 200
    assert literal_wildcard.json()["total"] == 0


def test_product_catalog_uses_only_selected_stores(client, catalog):
    store_a, _, first, _ = catalog

    response = client.get("/izdelki", params={"trgovina_ids": store_a.id, "q": "same", "limit": 10})

    assert response.status_code == 200, response.text
    first_product = next(item for item in response.json()["items"] if item["id"] == first.id)
    assert first_product["najcenejsa_ponudba"]["trgovina_id"] == store_a.id
    assert first_product["najcenejsa_ponudba"]["cena"] == "1.10"
    assert [offer["trgovina_id"] for offer in first_product["ponudbe"]] == [store_a.id]
    assert client.get("/izdelki", params={"trgovina_ids": 999999}).status_code == 404


def test_product_catalog_hides_source_less_demo_products(client, db, catalog):
    store_a, _, _, _ = catalog
    demo = Izdelek(ime="Demo milk", kategorija="demo", enota="1 l")
    db.add(demo)
    db.flush()
    db.add(Cena(izdelek_id=demo.id, trgovina_id=store_a.id, cena=Decimal("0.10"), datum_zajema=date.today()))
    db.commit()

    response = client.get("/izdelki", params={"q": "Demo milk"})

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []
