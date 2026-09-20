from datetime import date
from decimal import Decimal

from backend.models import Cena, RetailerProduct, Trgovina


def test_comparison_uses_latest_prices_quantities_ids_and_decimal_money(client, catalog):
    store_a, store_b, first, second = catalog
    response = client.post(
        "/primerjava",
        json={
            "items": [
                {"izdelek_id": first.id, "kolicina": 3},
                {"izdelek_id": second.id, "kolicina": 2},
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["najcenejsa_trgovina_id"] == store_a.id
    assert body["cene_po_trgovinah"] == [
        {"trgovina_id": store_a.id, "ime_trgovina": "Store A", "skupna_cena": "7.70"},
        {"trgovina_id": store_b.id, "ime_trgovina": "Store B", "skupna_cena": "9.00"},
    ]
    assert body["prihranek"] == "1.30"
    assert [row["izdelek_id"] for row in body["razdeljen_seznam"]] == [first.id, second.id]
    assert body["skupna_cena_razdeljeno"] == "7.40"
    assert body["dodatni_prihranek"] == "0.30"
    # Same product names remain distinct because comparison keys and output use IDs.
    assert [row["ime_izdelek"] for row in body["razdeljen_seznam"]] == ["Same name", "Same name"]

    prices = client.get("/cene").json()
    first_a = next(
        row for row in prices if row["izdelek_id"] == first.id and row["trgovina_id"] == store_a.id
    )
    assert first_a["cena"] == "1.10"
    assert first_a["datum_zajema"] == "2025-02-01"


def test_comparison_excludes_incomplete_stores_and_has_stable_ties(client, db, catalog):
    store_a, _, first, second = catalog
    incomplete = Trgovina(ime="Incomplete")
    tie = Trgovina(ime="Tie")
    db.add_all([incomplete, tie])
    db.flush()
    db.add_all(
        [
            Cena(izdelek_id=first.id, trgovina_id=incomplete.id, cena=Decimal("0.01"), datum_zajema=date(2025, 2, 1)),
            Cena(izdelek_id=first.id, trgovina_id=tie.id, cena=Decimal("1.10"), datum_zajema=date(2025, 2, 1)),
            Cena(izdelek_id=second.id, trgovina_id=tie.id, cena=Decimal("2.20"), datum_zajema=date(2025, 2, 1)),
        ]
    )
    db.commit()
    response = client.post(
        "/primerjava",
        json={"items": [{"izdelek_id": first.id}, {"izdelek_id": second.id}]},
    )
    assert response.status_code == 200
    ids = [row["trgovina_id"] for row in response.json()["cene_po_trgovinah"]]
    assert incomplete.id not in ids
    assert response.json()["najcenejsa_trgovina_id"] == min(store_a.id, tie.id)


def test_comparison_returns_split_when_no_store_covers_every_product(client, db, catalog):
    store_a, store_b, first, second = catalog
    db.query(Cena).filter(Cena.izdelek_id == first.id, Cena.trgovina_id == store_b.id).delete()
    db.query(Cena).filter(Cena.izdelek_id == second.id, Cena.trgovina_id == store_a.id).delete()
    db.commit()

    response = client.post(
        "/primerjava",
        json={"items": [{"izdelek_id": first.id}, {"izdelek_id": second.id}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["celoten_nakup_na_voljo"] is False
    assert body["cene_po_trgovinah"] == []
    assert body["najcenejsa_trgovina_id"] is None
    assert body["najcenejsa_trgovina"] is None
    assert body["prihranek"] is None
    assert body["dodatni_prihranek"] is None
    assert body["skupna_cena_razdeljeno"] == "4.10"
    assert [item["ime_trgovina"] for item in body["razdeljen_seznam"]] == ["Store A", "Store B"]


def test_comparison_is_limited_to_selected_stores(client, catalog):
    store_a, store_b, first, second = catalog

    response = client.post(
        "/primerjava",
        json={
            "items": [{"izdelek_id": first.id}, {"izdelek_id": second.id}],
            "trgovina_ids": [store_b.id],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cene_po_trgovinah"] == [
        {"trgovina_id": store_b.id, "ime_trgovina": "Store B", "skupna_cena": "4.00"}
    ]
    assert {item["trgovina_id"] for item in body["razdeljen_seznam"]} == {store_b.id}
    assert body["najcenejsa_trgovina_id"] == store_b.id
    assert store_a.id != store_b.id


def test_comparison_rejects_invalid_store_selection(client, catalog):
    _, _, first, _ = catalog
    item = {"items": [{"izdelek_id": first.id}]}

    assert client.post("/primerjava", json={**item, "trgovina_ids": []}).status_code == 422
    assert client.post("/primerjava", json={**item, "trgovina_ids": [1, 1]}).status_code == 422
    assert client.post("/primerjava", json={**item, "trgovina_ids": [999999]}).status_code == 404


def test_comparison_errors_are_defined(client, db, catalog):
    _, _, first, second = catalog
    assert client.post(
        "/primerjava", json={"items": [{"izdelek_id": 999999, "kolicina": 1}]}
    ).status_code == 404
    assert client.post(
        "/primerjava",
        json={"items": [{"izdelek_id": first.id}, {"izdelek_id": first.id}]},
    ).status_code == 422

    db.query(Cena).filter(Cena.izdelek_id == second.id).delete()
    db.commit()
    unavailable = client.post(
        "/primerjava",
        json={"items": [{"izdelek_id": first.id}, {"izdelek_id": second.id}]},
    )
    assert unavailable.status_code == 422
    assert "No current price" in unavailable.json()["detail"]


def test_prices_endpoint_excludes_inactive_offers(client, db, catalog):
    store_a, _, first, _ = catalog
    source = db.query(RetailerProduct).filter_by(
        trgovina_id=store_a.id,
        izdelek_id=first.id,
    ).one()
    source.is_active = False
    db.commit()

    prices = client.get("/cene").json()

    assert not any(
        row["izdelek_id"] == first.id and row["trgovina_id"] == store_a.id
        for row in prices
    )
