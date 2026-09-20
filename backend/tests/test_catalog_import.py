from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.catalog_import import (
    CatalogProduct,
    PriceObservation,
    create_import_run,
    normalize_gtin,
    persist_import,
    run_import,
)
from backend.models import (
    CatalogImportRun,
    Cena,
    Izdelek,
    ProductGtin,
    RetailerPriceSnapshot,
    RetailerProduct,
    RetailerProductGtin,
    Trgovina,
)


def product(external_id, gtin, price="2.50"):
    return CatalogProduct(
        external_id=external_id,
        name=f"Product {external_id}",
        gtins=(gtin,),
        category="Food",
        unit="piece",
        price=PriceObservation(
            effective_price=Decimal(price),
            regular_price=Decimal("3.00"),
        ),
    )


def test_gtin_validation_uses_exact_checksums():
    assert normalize_gtin("3838975531314") == "3838975531314"
    assert normalize_gtin("08052575091176") == "08052575091176"
    assert normalize_gtin("3838975531315") is None
    assert normalize_gtin("383 897 553 1314") is None


def test_import_matches_gtins_keeps_history_and_deactivates_only_after_success(db):
    run = create_import_run(db, "Test Store", date(2026, 9, 18))
    first = persist_import(
        db,
        run,
        [
            product("one", "3838975531314", "2.50"),
            product("duplicate", "3838975531314", "2.25"),
            product("invalid", "3838975531315", "1.00"),
        ],
    )
    db.commit()

    assert first.products_seen == 3
    assert first.products_mapped == 2
    assert db.scalar(select(func.count()).select_from(Izdelek)) == 1
    assert db.scalar(select(func.count()).select_from(ProductGtin)) == 1
    assert db.scalar(select(func.count()).select_from(RetailerPriceSnapshot)) == 3
    assert db.scalar(select(Cena.cena)) == Decimal("2.25")
    invalid = db.scalar(select(RetailerProduct).where(RetailerProduct.external_id == "invalid"))
    assert invalid.izdelek_id is None

    rerun = create_import_run(db, "Test Store", date(2026, 9, 18))
    persist_import(
        db,
        rerun,
        [product("one", "3838975531314", "2.75")],
        deactivate_missing=True,
    )
    db.commit()

    assert db.scalar(select(func.count()).select_from(RetailerPriceSnapshot)) == 3
    assert db.scalar(select(Cena.cena)) == Decimal("2.75")
    inactive = db.scalars(select(RetailerProduct).where(RetailerProduct.is_active.is_(False))).all()
    assert {item.external_id for item in inactive} == {"duplicate", "invalid"}


def test_failed_crawl_records_failure_without_deactivating_products(db):
    initial = create_import_run(db, "Failure Store", date(2026, 9, 17))
    persist_import(db, initial, [product("one", "8052575091176")])
    db.commit()

    class EmptyAdapter:
        retailer_name = "Failure Store"

        def fetch_catalog(self):
            return []

    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    with pytest.raises(RuntimeError, match="empty catalog"):
        run_import(EmptyAdapter(), factory, db.get_bind(), date(2026, 9, 18))

    db.expire_all()
    source_product = db.scalar(select(RetailerProduct).where(RetailerProduct.external_id == "one"))
    failed_run = db.scalar(
        select(CatalogImportRun)
        .where(CatalogImportRun.captured_on == date(2026, 9, 18))
        .order_by(CatalogImportRun.id.desc())
    )
    assert source_product.is_active is True
    assert failed_run.status == "failed"


def test_partial_nonempty_crawl_fails_without_deactivating_previous_catalog(db):
    initial = create_import_run(db, "Partial Store", date(2026, 9, 17))
    persist_import(
        db,
        initial,
        [product(str(index), "3838975531314") for index in range(4)],
    )
    db.commit()

    class PartialAdapter:
        retailer_name = "Partial Store"
        catalog_is_complete = True

        def fetch_catalog(self):
            return [product("0", "3838975531314")]

    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    with pytest.raises(RuntimeError, match="implausibly small"):
        run_import(PartialAdapter(), factory, db.get_bind(), date(2026, 9, 18))

    db.expire_all()
    assert set(db.scalars(select(RetailerProduct.is_active))) == {True}
    failed = db.scalar(
        select(CatalogImportRun).order_by(CatalogImportRun.id.desc()).limit(1)
    )
    assert failed.status == "failed"


def test_small_first_import_is_allowed_and_abandoned_run_is_closed(db):
    abandoned = create_import_run(db, "New Store", date(2026, 9, 17))
    abandoned_id = abandoned.id
    db.commit()

    class SmallAdapter:
        retailer_name = "New Store"
        catalog_is_complete = True

        def fetch_catalog(self):
            return [product("one", "3838975531314")]

    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    result = run_import(SmallAdapter(), factory, db.get_bind(), date(2026, 9, 18))

    db.expire_all()
    assert result.status == "completed"
    assert db.get(CatalogImportRun, abandoned_id).status == "failed"
    assert db.get(CatalogImportRun, abandoned_id).error_message == "Abandoned by a newer import"


def test_changed_and_conflicting_gtins_are_quarantined(db):
    first_run = create_import_run(db, "GTIN Store", date(2026, 9, 17))
    persist_import(
        db,
        first_run,
        [
            product("one", "3838975531314"),
            product("two", "08052575091176"),
        ],
    )
    db.commit()
    first_source = db.scalar(
        select(RetailerProduct).where(RetailerProduct.external_id == "one")
    )
    original_canonical_id = first_source.izdelek_id

    conflict_run = create_import_run(db, "GTIN Store", date(2026, 9, 18))
    conflict = persist_import(
        db,
        conflict_run,
        [product("one", "08052575091176")],
    )
    db.commit()

    db.refresh(first_source)
    assert first_source.izdelek_id == original_canonical_id
    assert first_source.gtin == "3838975531314"
    assert any("conflicts with canonical" in warning for warning in conflict.warnings)
    source_aliases = set(
        db.scalars(
            select(RetailerProductGtin.gtin).where(
                RetailerProductGtin.retailer_product_id == first_source.id
            )
        )
    )
    assert source_aliases == {"3838975531314"}

    changed_run = create_import_run(db, "GTIN Store", date(2026, 9, 19))
    changed = persist_import(
        db,
        changed_run,
        [product("one", "4006381333931")],
    )
    db.commit()
    assert any("quarantined" in warning for warning in changed.warnings)
    assert db.scalar(select(func.count()).select_from(ProductGtin)) == 2
    assert db.scalar(select(func.count()).select_from(Cena)) == 2


def test_first_import_uses_existing_active_catalog_as_safety_baseline(db):
    store = Trgovina(ime="Migrated Store")
    db.add(store)
    db.flush()
    db.add_all(
        [
            RetailerProduct(
                trgovina_id=store.id,
                external_id=str(index),
                ime=f"Legacy {index}",
                is_active=True,
            )
            for index in range(5)
        ]
    )
    db.commit()

    class PartialFirstAdapter:
        retailer_name = "Migrated Store"
        catalog_is_complete = True

        def fetch_catalog(self):
            return [product("0", "3838975531314")]

    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    with pytest.raises(RuntimeError, match="implausibly small"):
        run_import(PartialFirstAdapter(), factory, db.get_bind(), date(2026, 9, 18))

    db.expire_all()
    assert set(db.scalars(select(RetailerProduct.is_active))) == {True}


def test_oversized_external_id_is_rejected_before_product_persistence(db):
    run = create_import_run(db, "ID Store", date(2026, 9, 18))

    with pytest.raises(ValueError, match="exceeds 100"):
        persist_import(db, run, [product("x" * 101, "3838975531314")])

    assert db.scalar(select(func.count()).select_from(RetailerProduct)) == 0
