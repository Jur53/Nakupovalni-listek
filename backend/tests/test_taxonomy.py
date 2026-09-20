import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from backend.catalog_import import CatalogProduct, PriceObservation, create_import_run, persist_import
from backend.models import Category, Cena, Izdelek, RetailerProduct, Trgovina
from backend.taxonomy import TAXONOMY_PATH, classify_products, load_taxonomy, sync_taxonomy


def add_offer(db, product, store, external_id, source_category, price="1.00"):
    db.add(
        RetailerProduct(
            trgovina_id=store.id,
            external_id=external_id,
            ime=product.ime,
            kategorija=source_category,
            izdelek_id=product.id,
            is_active=True,
        )
    )
    db.add(
        Cena(
            izdelek_id=product.id,
            trgovina_id=store.id,
            cena=Decimal(price),
            datum_zajema=date(2026, 9, 20),
        )
    )


def test_taxonomy_definition_validation_rejects_unknown_targets_and_ambiguity(tmp_path):
    valid = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    valid["source_category_rules"][0]["category"] = "missing-category"
    unknown_path = tmp_path / "unknown.json"
    unknown_path.write_text(json.dumps(valid), encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown taxonomy rule category"):
        load_taxonomy(unknown_path)

    valid = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    valid["source_category_rules"].append(
        {"category": "produce", "keywords": ["OBLAČILA"]}
    )
    ambiguous_path = tmp_path / "ambiguous.json"
    ambiguous_path.write_text(json.dumps(valid), encoding="utf-8")

    with pytest.raises(ValueError, match="Ambiguous normalized keyword"):
        load_taxonomy(ambiguous_path)


def test_sync_and_backfill_are_idempotent_and_normalize_source_labels(db):
    store = Trgovina(ime="Taxonomy Store")
    products = [
        Izdelek(ime="Frozen one"),
        Izdelek(ime="Frozen two"),
        Izdelek(ime="Dairy one"),
        Izdelek(ime="Dairy two"),
        Izdelek(ime="Work jacket"),
    ]
    db.add_all([store, *products])
    db.flush()
    labels = [
        "ZAMRZNJENA HRANA",
        "zamrznjeni izdelki",
        "MLEČNI IZDELKI",
        "Mleko in mlečni izdelki",
        "OBLAČILA",
    ]
    for index, (product, label) in enumerate(zip(products, labels, strict=True)):
        add_offer(db, product, store, str(index), label)

    first_categories = sync_taxonomy(db)
    first = classify_products(db, categories_by_slug=first_categories)
    first_ids = {slug: category.id for slug, category in first_categories.items()}
    second_categories = sync_taxonomy(db)
    second = classify_products(db, categories_by_slug=second_categories)

    assert first.changed == len(products)
    assert second.changed == 0
    assert first_ids == {slug: category.id for slug, category in second_categories.items()}
    assert products[0].category_id == products[1].category_id == first_categories["frozen"].id
    assert products[2].category_id == products[3].category_id == first_categories["dairy-eggs-chilled"].id
    assert products[4].category_id == first_categories["clothing"].id
    assert first.hidden == 1


def test_product_name_refines_only_within_the_source_category_branch(db):
    store = Trgovina(ime="Refinement Store")
    yogurt = Izdelek(ime="Navadni jogurt 3,2%")
    detergent = Izdelek(ime="Jogurt named detergent")
    db.add_all([store, yogurt, detergent])
    db.flush()
    add_offer(db, yogurt, store, "yogurt", "MLEČNI IZDELKI")
    add_offer(db, detergent, store, "detergent", "Dom in čiščenje")

    categories = sync_taxonomy(db)
    classify_products(db, {yogurt.id, detergent.id}, categories_by_slug=categories)

    assert yogurt.category_id == categories["yogurt"].id
    assert detergent.category_id == categories["home-cleaning"].id


def test_specific_retailer_source_outweighs_a_generic_legacy_source(db):
    store = Trgovina(ime="Source Priority Store")
    wine = Izdelek(ime="House label red", kategorija="PIJAČE")
    db.add_all([store, wine])
    db.flush()
    add_offer(db, wine, store, "wine", "ALKOHOLNE PIJAČE")

    categories = sync_taxonomy(db)
    classify_products(db, {wine.id}, categories_by_slug=categories)

    assert wine.category_id == categories["alcohol"].id


def test_name_can_resolve_conflicting_sources_when_it_agrees_with_one_branch(db):
    store = Trgovina(ime="Conflicting Sources Store")
    coffee = Izdelek(ime="Mleta kava", kategorija="OSNOVNA ŽIVILA / SHRAMBA")
    broad_produce = Izdelek(ime="Tedenska košarica", kategorija="SADJE IN ZELENJAVA")
    specialty = Izdelek(ime="Neuvrščen poseben izdelek", kategorija="EKOLOŠKA ŽIVILA")
    db.add_all([store, coffee, broad_produce, specialty])
    db.flush()
    add_offer(db, coffee, store, "coffee", "VSE ZA ZAJTRK")
    add_offer(db, broad_produce, store, "produce", "SADJE IN ZELENJAVA")

    categories = sync_taxonomy(db)
    classify_products(
        db, {coffee.id, broad_produce.id, specialty.id}, categories_by_slug=categories
    )

    assert coffee.category_id == categories["coffee-tea-cocoa"].id
    assert broad_produce.category_id == categories["produce"].id
    assert specialty.category_id == categories["pantry"].id


def test_category_tree_descendant_filters_store_counts_and_hidden_catalog(client, db):
    categories = sync_taxonomy(db)
    store_a = Trgovina(ime="Store A")
    store_b = Trgovina(ime="Store B")
    apple = Izdelek(ime="Jabolko gala")
    carrot = Izdelek(ime="Sveže korenje")
    milk = Izdelek(ime="Polnomastno mleko")
    jacket = Izdelek(ime="Zimska jakna")
    db.add_all([store_a, store_b, apple, carrot, milk, jacket])
    db.flush()
    add_offer(db, apple, store_a, "a-apple", "Sveže sadje")
    add_offer(db, apple, store_b, "b-apple", "Sadje")
    add_offer(db, carrot, store_b, "b-carrot", "Sveža zelenjava")
    add_offer(db, milk, store_a, "a-milk", "Mleko")
    add_offer(db, jacket, store_a, "a-jacket", "Oblačila")
    classify_products(db, {apple.id, carrot.id, milk.id, jacket.id}, categories_by_slug=categories)
    db.commit()

    all_tree = client.get("/categories")
    assert all_tree.status_code == 200
    roots = {node["slug"]: node for node in all_tree.json()}
    assert roots["produce"]["product_count"] == 2
    assert roots["dairy-eggs-chilled"]["product_count"] == 1
    assert "review-out-of-scope" not in roots

    store_a_tree = client.get("/categories", params={"trgovina_ids": store_a.id}).json()
    store_b_tree = client.get("/categories", params={"trgovina_ids": store_b.id}).json()
    both_tree = client.get(
        "/categories",
        params=[("trgovina_ids", store_a.id), ("trgovina_ids", store_b.id)],
    ).json()
    assert next(node for node in store_a_tree if node["slug"] == "produce")["product_count"] == 1
    assert next(node for node in store_b_tree if node["slug"] == "produce")["product_count"] == 2
    assert next(node for node in both_tree if node["slug"] == "produce")["product_count"] == 2
    assert "dairy-eggs-chilled" not in {node["slug"] for node in store_b_tree}

    filtered = client.get(
        "/izdelki",
        params={"kategorija_id": categories["produce"].id, "limit": 100},
    )
    assert filtered.status_code == 200
    assert {item["id"] for item in filtered.json()["items"]} == {apple.id, carrot.id}
    apple_out = next(item for item in filtered.json()["items"] if item["id"] == apple.id)
    assert apple_out["kategorija_id"] == categories["fresh-fruit"].id
    assert apple_out["kategorija_pot"] == ["Sadje in zelenjava", "Sveže sadje"]
    assert filtered.json()["category_tree"]

    catalog = client.get("/izdelki", params={"limit": 100}).json()
    assert jacket.id not in {item["id"] for item in catalog["items"]}
    assert catalog["total"] == 3
    assert client.get("/izdelki", params={"kategorija_id": 999999}).status_code == 404


def test_import_classifies_only_canonical_products_touched_by_the_import(db):
    categories = sync_taxonomy(db)
    untouched = Izdelek(
        ime="Mleko that should not be rescanned",
        category_id=categories["review-out-of-scope"].id,
    )
    db.add(untouched)
    db.flush()
    untouched_id = untouched.id
    run = create_import_run(db, "Import Store", date(2026, 9, 20))

    persist_import(
        db,
        run,
        [
            CatalogProduct(
                external_id="milk",
                name="Test mleko 1 l",
                category="MLEČNI IZDELKI",
                gtins=("3838975531314",),
                price=PriceObservation(effective_price=Decimal("1.20")),
            )
        ],
    )
    db.commit()

    imported = db.scalar(
        select(Izdelek).where(Izdelek.id != untouched_id).order_by(Izdelek.id.desc())
    )
    assert imported.category_id == categories["milk"].id
    assert db.get(Izdelek, untouched_id).category_id == categories["review-out-of-scope"].id
    assert db.scalar(select(func.count()).select_from(Category)) == len(load_taxonomy().categories)
