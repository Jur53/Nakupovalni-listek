"""Shared retailer import types, GTIN matching, and persistence."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Protocol

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    CatalogImportRun,
    Cena,
    Izdelek,
    ProductGtin,
    RetailerPriceSnapshot,
    RetailerProduct,
    RetailerProductGtin,
    Trgovina,
)
from .product_mappings import apply_curated_mappings
from .taxonomy import classify_products, sync_taxonomy


logger = logging.getLogger(__name__)

MAX_EXTERNAL_ID_LENGTH = 100
MIN_CATALOG_RETENTION_RATIO = Decimal("0.80")


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class PriceObservation:
    effective_price: Decimal
    regular_price: Decimal | None = None
    promotion_price: Decimal | None = None
    previous_price: Decimal | None = None
    lowest_30d_price: Decimal | None = None
    unit_price: Decimal | None = None
    unit_base: str | None = None
    currency: str = "EUR"
    promotion_type: str | None = None
    promotion_starts_at: datetime | None = None
    promotion_ends_at: datetime | None = None
    requires_loyalty: bool = False
    promotion_data: dict | list | None = None


@dataclass(frozen=True)
class CatalogProduct:
    external_id: str
    name: str
    price: PriceObservation
    gtins: tuple[str, ...] = ()
    brand: str | None = None
    category: str | None = None
    unit: str | None = None
    url: str | None = None
    image_url: str | None = None


class CatalogAdapter(Protocol):
    retailer_name: str
    catalog_is_complete: bool

    def fetch_catalog(self) -> list[CatalogProduct]: ...


@dataclass
class ImportResult:
    retailer: str
    run_id: int
    status: str
    products_seen: int = 0
    products_mapped: int = 0
    snapshots_written: int = 0
    prices_written: int = 0
    warnings: list[str] = field(default_factory=list)


def normalize_gtin(value: object) -> str | None:
    """Return a checksum-valid GTIN-8/12/13/14 without changing leading zeroes."""
    gtin = str(value).strip() if value is not None else ""
    if len(gtin) not in {8, 12, 13, 14} or not gtin.isdigit():
        return None
    expected = int(gtin[-1])
    total = 0
    for index, digit in enumerate(reversed(gtin[:-1])):
        total += int(digit) * (3 if index % 2 == 0 else 1)
    return gtin if (10 - total % 10) % 10 == expected else None


def valid_gtins(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result = []
    for value in values:
        gtin = normalize_gtin(value)
        if gtin and gtin not in result:
            result.append(gtin)
    return tuple(result)


def _limited(value: str | None, length: int) -> str | None:
    value = value.strip() if isinstance(value, str) else None
    return value[:length] if value else None


def _get_or_create_store(db: Session, name: str) -> Trgovina:
    store = db.scalar(select(Trgovina).where(Trgovina.ime == name))
    if store is None:
        store = Trgovina(ime=name)
        db.add(store)
        db.flush()
    return store


def create_import_run(
    db: Session,
    retailer: str,
    captured_on: date,
    *,
    abandon_running: bool = True,
) -> CatalogImportRun:
    store = _get_or_create_store(db, retailer)
    now = _utc_now()
    if abandon_running:
        for abandoned in db.scalars(
            select(CatalogImportRun).where(
                CatalogImportRun.trgovina_id == store.id,
                CatalogImportRun.status == "running",
            )
        ):
            abandoned.status = "failed"
            abandoned.completed_at = now
            abandoned.error_message = "Abandoned by a newer import"
    run = CatalogImportRun(trgovina_id=store.id, status="running", captured_on=captured_on)
    db.add(run)
    db.flush()
    return run


def _map_canonical_product(
    db: Session,
    retailer_product: RetailerProduct,
    product: CatalogProduct,
    gtins: tuple[str, ...],
    canonical_by_gtin: dict[str, ProductGtin],
    known_source_gtins: set[str],
    warnings: list[str],
) -> tuple[int | None, tuple[str, ...]]:
    matched_ids = {canonical_by_gtin[gtin].izdelek_id for gtin in gtins if gtin in canonical_by_gtin}
    was_mapped = retailer_product.izdelek_id is not None

    if retailer_product.izdelek_id is not None:
        canonical_id = retailer_product.izdelek_id
        conflicting = matched_ids - {canonical_id}
        if conflicting:
            warnings.append(
                f"{product.external_id}: GTIN conflicts with canonical products {sorted(conflicting)}"
            )
            accepted = tuple(
                gtin
                for gtin in gtins
                if gtin in canonical_by_gtin
                and canonical_by_gtin[gtin].izdelek_id == canonical_id
            )
            return (canonical_id if accepted else None), accepted
    elif len(matched_ids) > 1:
        warnings.append(
            f"{product.external_id}: GTINs resolve to multiple canonical products {sorted(matched_ids)}"
        )
        return None, ()
    elif matched_ids:
        canonical_id = next(iter(matched_ids))
        retailer_product.izdelek_id = canonical_id
    elif gtins:
        canonical = Izdelek(
            ime=product.name[:200],
            kategorija=_limited(product.category, 100),
            enota=_limited(product.unit, 20),
        )
        db.add(canonical)
        db.flush()
        canonical_id = canonical.id
        retailer_product.izdelek_id = canonical_id
    else:
        return retailer_product.izdelek_id, ()

    had_valid_gtins = bool(gtins)
    unmatched = tuple(gtin for gtin in gtins if gtin not in canonical_by_gtin)
    if was_mapped or matched_ids:
        quarantined = unmatched
    elif known_source_gtins:
        quarantined = tuple(gtin for gtin in unmatched if gtin not in known_source_gtins)
    else:
        quarantined = ()
    if quarantined:
        warnings.append(
            f"{product.external_id}: changed GTINs quarantined pending identity review: {list(quarantined)}"
        )
        gtins = tuple(gtin for gtin in gtins if gtin not in quarantined)

    for gtin in gtins:
        existing = canonical_by_gtin.get(gtin)
        if existing is not None:
            if existing.izdelek_id != canonical_id:
                warnings.append(
                    f"{product.external_id}: GTIN {gtin} belongs to canonical product {existing.izdelek_id}"
                )
            continue
        alias = ProductGtin(izdelek_id=canonical_id, gtin=gtin)
        db.add(alias)
        canonical_by_gtin[gtin] = alias
    return (canonical_id if gtins or not had_valid_gtins else None), gtins


def _validated_products(products: list[CatalogProduct]) -> None:
    for product in products:
        external_id = product.external_id.strip()
        if not external_id:
            raise ValueError("Catalog product external_id cannot be empty")
        if len(external_id) > MAX_EXTERNAL_ID_LENGTH:
            raise ValueError(
                f"Catalog product external_id exceeds {MAX_EXTERNAL_ID_LENGTH} characters"
            )


def persist_import(
    db: Session,
    run: CatalogImportRun,
    products: list[CatalogProduct],
    *,
    deactivate_missing: bool = False,
) -> ImportResult:
    """Persist retailer observations, optionally deactivating unseen source rows."""
    _validated_products(products)
    store = db.get(Trgovina, run.trgovina_id)
    if store is None:
        raise RuntimeError("Import run references a missing retailer")

    result = ImportResult(retailer=store.ime, run_id=run.id, status="running")
    taxonomy_categories = sync_taxonomy(db)
    existing_products = {
        product.external_id: product
        for product in db.scalars(
            select(RetailerProduct).where(RetailerProduct.trgovina_id == store.id)
        )
    }
    prepared_external_ids: set[str] = set()
    for product in products:
        external_id = product.external_id.strip()
        if external_id in prepared_external_ids:
            continue
        prepared_external_ids.add(external_id)
        retailer_product = existing_products.get(external_id)
        created = retailer_product is None
        if retailer_product is None:
            retailer_product = RetailerProduct(
                trgovina_id=store.id,
                external_id=external_id,
                ime=product.name[:300],
            )
            db.add(retailer_product)
            existing_products[external_id] = retailer_product
        retailer_product.ime = product.name[:300]
        incoming_gtins = valid_gtins(product.gtins)
        if created and incoming_gtins:
            retailer_product.gtin = incoming_gtins[0]
    db.flush()
    curated_assignments = apply_curated_mappings(db)
    existing_products = {
        product.external_id: product
        for product in db.scalars(
            select(RetailerProduct).where(RetailerProduct.trgovina_id == store.id)
        )
    }
    canonical_by_gtin = {
        alias.gtin: alias for alias in db.scalars(select(ProductGtin))
    }
    existing_source_gtins = {
        (row.retailer_product_id, row.gtin)
        for row in db.scalars(
            select(RetailerProductGtin)
            .join(RetailerProduct)
            .where(RetailerProduct.trgovina_id == store.id)
        )
    }
    source_gtins_by_product: dict[int, set[str]] = {}
    for retailer_product_id, gtin in existing_source_gtins:
        source_gtins_by_product.setdefault(retailer_product_id, set()).add(gtin)
    snapshots_by_product = {
        snapshot.retailer_product_id: snapshot
        for snapshot in db.scalars(
            select(RetailerPriceSnapshot)
            .join(RetailerProduct)
            .where(
                RetailerProduct.trgovina_id == store.id,
                RetailerPriceSnapshot.captured_on == run.captured_on,
            )
        )
    }
    prices_by_product = {
        price.izdelek_id: price
        for price in db.scalars(
            select(Cena).where(
                Cena.trgovina_id == store.id,
                Cena.datum_zajema == run.captured_on,
            )
        )
    }
    current_prices: dict[int, Decimal] = {}
    touched_canonical_ids: set[int] = set()
    seen_external_ids: set[str] = set()

    for product in products:
        external_id = product.external_id.strip()
        if not external_id or external_id in seen_external_ids:
            continue
        seen_external_ids.add(external_id)
        retailer_product = existing_products.get(external_id)
        if retailer_product is None:
            retailer_product = RetailerProduct(
                trgovina_id=store.id,
                external_id=external_id,
                ime=product.name[:300],
            )
            db.add(retailer_product)
            db.flush()
            existing_products[external_id] = retailer_product

        gtins = valid_gtins(product.gtins)
        retailer_product.ime = product.name[:300]
        retailer_product.brand = _limited(product.brand, 200)
        retailer_product.kategorija = _limited(product.category, 300)
        retailer_product.enota = _limited(product.unit, 50)
        retailer_product.url = _limited(product.url, 1000)
        retailer_product.image_url = _limited(product.image_url, 1000)
        retailer_product.is_active = True
        retailer_product.last_seen_at = _utc_now()
        retailer_product.last_seen_run_id = run.id

        curated_canonical_id = curated_assignments.get(retailer_product.id)
        if curated_canonical_id is not None:
            accepted: list[str] = []
            for gtin in gtins:
                existing_alias = canonical_by_gtin.get(gtin)
                if existing_alias is None:
                    existing_alias = ProductGtin(
                        izdelek_id=curated_canonical_id,
                        gtin=gtin,
                    )
                    db.add(existing_alias)
                    canonical_by_gtin[gtin] = existing_alias
                    accepted.append(gtin)
                elif existing_alias.izdelek_id == curated_canonical_id:
                    accepted.append(gtin)
                else:
                    result.warnings.append(
                        f"{product.external_id}: curated mapping rejected conflicting GTIN {gtin}"
                    )
            canonical_id = curated_canonical_id
            accepted_gtins = tuple(accepted)
            retailer_product.gtin = accepted_gtins[0] if accepted_gtins else None
        else:
            canonical_id, accepted_gtins = _map_canonical_product(
                db,
                retailer_product,
                product,
                gtins,
                canonical_by_gtin,
                source_gtins_by_product.get(retailer_product.id, set()),
                result.warnings,
            )
            if accepted_gtins:
                retailer_product.gtin = accepted_gtins[0]
        for gtin in accepted_gtins:
            key = (retailer_product.id, gtin)
            if key not in existing_source_gtins:
                db.add(RetailerProductGtin(retailer_product_id=retailer_product.id, gtin=gtin))
                existing_source_gtins.add(key)
                source_gtins_by_product.setdefault(retailer_product.id, set()).add(gtin)

        snapshot = snapshots_by_product.get(retailer_product.id)
        if snapshot is None:
            snapshot = RetailerPriceSnapshot(
                retailer_product_id=retailer_product.id,
                captured_on=run.captured_on,
                effective_price=product.price.effective_price,
            )
            db.add(snapshot)
            snapshots_by_product[retailer_product.id] = snapshot
        snapshot.captured_at = _utc_now()
        snapshot.effective_price = product.price.effective_price
        snapshot.regular_price = product.price.regular_price
        snapshot.promotion_price = product.price.promotion_price
        snapshot.previous_price = product.price.previous_price
        snapshot.lowest_30d_price = product.price.lowest_30d_price
        snapshot.unit_price = product.price.unit_price
        snapshot.unit_base = _limited(product.price.unit_base, 50)
        snapshot.currency = product.price.currency[:3]
        snapshot.promotion_type = _limited(product.price.promotion_type, 100)
        snapshot.promotion_starts_at = product.price.promotion_starts_at
        snapshot.promotion_ends_at = product.price.promotion_ends_at
        snapshot.requires_loyalty = product.price.requires_loyalty
        snapshot.promotion_data = product.price.promotion_data

        if canonical_id is not None:
            touched_canonical_ids.add(canonical_id)
            current = current_prices.get(canonical_id)
            if current is None or product.price.effective_price < current:
                current_prices[canonical_id] = product.price.effective_price

    if deactivate_missing:
        for retailer_product in existing_products.values():
            if retailer_product.external_id not in seen_external_ids:
                retailer_product.is_active = False

    for canonical_id, amount in current_prices.items():
        price = prices_by_product.get(canonical_id)
        if price is None:
            price = Cena(
                izdelek_id=canonical_id,
                trgovina_id=store.id,
                datum_zajema=run.captured_on,
                cena=amount,
            )
            db.add(price)
            prices_by_product[canonical_id] = price
        else:
            price.cena = amount

    classify_products(
        db,
        touched_canonical_ids,
        categories_by_slug=taxonomy_categories,
    )

    result.products_seen = len(seen_external_ids)
    result.products_mapped = sum(
        1
        for external_id in seen_external_ids
        if existing_products[external_id].izdelek_id is not None
    )
    result.snapshots_written = len(seen_external_ids)
    result.prices_written = len(current_prices)
    result.status = "completed"
    run.status = "completed"
    run.completed_at = _utc_now()
    run.products_seen = result.products_seen
    run.products_mapped = result.products_mapped
    run.snapshots_written = result.snapshots_written
    run.prices_written = result.prices_written
    run.error_message = "\n".join(result.warnings[:20]) or None
    db.flush()
    return result


def _lock_key(retailer: str) -> int:
    value = 0
    for byte in f"nakupovalni-listek:{retailer}".encode("utf-8"):
        value = (value * 31 + byte) & 0x7FFFFFFF
    return value


def _previous_completed_size(db: Session, store_id: int) -> int | None:
    recent_sizes = list(db.scalars(
        select(CatalogImportRun.products_seen)
        .where(
            CatalogImportRun.trgovina_id == store_id,
            CatalogImportRun.status == "completed",
        )
        .order_by(CatalogImportRun.id.desc())
        .limit(5)
    ))
    if recent_sizes:
        return max(recent_sizes)
    existing_active = db.scalar(
        select(func.count())
        .select_from(RetailerProduct)
        .where(
            RetailerProduct.trgovina_id == store_id,
            RetailerProduct.is_active.is_(True),
        )
    )
    return existing_active or None


def _validate_crawl_health(
    adapter: CatalogAdapter,
    products: list[CatalogProduct],
    previous_size: int | None,
) -> None:
    if not products:
        raise RuntimeError("Retailer returned an empty catalog")
    if getattr(adapter, "catalog_is_complete", False) is not True:
        raise RuntimeError("Retailer adapter did not declare the catalog complete")
    if previous_size:
        minimum = max(
            1,
            int(
                (Decimal(previous_size) * MIN_CATALOG_RETENTION_RATIO).to_integral_value(
                    rounding=ROUND_CEILING
                )
            ),
        )
        if len({product.external_id.strip() for product in products}) < minimum:
            raise RuntimeError(
                f"Retailer catalog is implausibly small compared with the previous successful import "
                f"({len(products)} received, at least {minimum} required)"
            )


def run_import(
    adapter: CatalogAdapter,
    session_factory: sessionmaker,
    engine: Engine,
    captured_on: date | None = None,
) -> ImportResult:
    captured_on = captured_on or date.today()
    lock_connection = engine.connect()
    locked = True
    lock_key = _lock_key(adapter.retailer_name)
    try:
        if engine.dialect.name == "postgresql":
            locked = bool(
                lock_connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})
            )
        if not locked:
            with session_factory.begin() as db:
                skipped_run = create_import_run(
                    db,
                    adapter.retailer_name,
                    captured_on,
                    abandon_running=False,
                )
                skipped_run.status = "skipped"
                skipped_run.completed_at = _utc_now()
                skipped_run.error_message = "Another import for this retailer is already running"
                run_id = skipped_run.id
            return ImportResult(retailer=adapter.retailer_name, run_id=run_id, status="skipped")

        with session_factory.begin() as db:
            run = create_import_run(db, adapter.retailer_name, captured_on)
            run_id = run.id
            store_id = run.trgovina_id
            previous_size = _previous_completed_size(db, store_id)

        try:
            products = adapter.fetch_catalog()
            _validated_products(products)
            _validate_crawl_health(adapter, products, previous_size)
            with session_factory.begin() as db:
                if engine.dialect.name == "postgresql":
                    for gtin in sorted(
                        {
                            gtin
                            for product in products
                            for gtin in valid_gtins(product.gtins)
                        }
                    ):
                        db.execute(
                            text("SELECT pg_advisory_xact_lock(:key)"),
                            {"key": _lock_key(f"gtin:{gtin}")},
                        )
                current_run = db.get(CatalogImportRun, run_id)
                if current_run is None:
                    raise RuntimeError("Import run disappeared before persistence")
                result = persist_import(
                    db,
                    current_run,
                    products,
                    deactivate_missing=True,
                )
            for warning in result.warnings:
                logger.warning("%s import: %s", adapter.retailer_name, warning)
            return result
        except Exception as exc:
            with session_factory.begin() as db:
                failed_run = db.get(CatalogImportRun, run_id)
                if failed_run is not None:
                    failed_run.status = "failed"
                    failed_run.completed_at = _utc_now()
                    failed_run.error_message = str(exc)[:4000]
            raise
    finally:
        if locked and engine.dialect.name == "postgresql":
            lock_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
        lock_connection.close()
