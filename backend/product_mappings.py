"""Curated source-product merges for products that GTIN matching cannot unify."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Cena,
    Izdelek,
    ProductGtin,
    RetailerProduct,
    SeznamIzdelek,
    Trgovina,
)


MAPPINGS_PATH = Path(__file__).with_name("product_mappings.json")


@dataclass(frozen=True)
class MappingMember:
    retailer: str
    external_id: str | None = None
    source_name: str | None = None
    gtin: str | None = None


@dataclass(frozen=True)
class ProductMapping:
    key: str
    name: str
    category: str | None
    unit: str | None
    members: tuple[MappingMember, ...]


def _optional_text(value: object, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"Invalid curated product {field}")
    return value.strip()


@lru_cache
def load_product_mappings(path: Path = MAPPINGS_PATH) -> tuple[ProductMapping, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Curated product mappings must be a JSON array")

    mappings: list[ProductMapping] = []
    keys: set[str] = set()
    claimed_members: set[tuple[str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each curated product mapping must be an object")
        key = _optional_text(item.get("key"), "key", 100)
        name = _optional_text(item.get("name"), "name", 200)
        if key is None or name is None or key in keys:
            raise ValueError("Curated product keys and names must be present and keys unique")
        keys.add(key)
        raw_members = item.get("members")
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError(f"Curated product {key} must contain members")

        members: list[MappingMember] = []
        for raw_member in raw_members:
            if not isinstance(raw_member, dict):
                raise ValueError(f"Invalid member in curated product {key}")
            retailer = _optional_text(raw_member.get("retailer"), "retailer", 100)
            external_id = _optional_text(raw_member.get("external_id"), "external_id", 100)
            source_name = _optional_text(raw_member.get("source_name"), "source_name", 300)
            gtin = _optional_text(raw_member.get("gtin"), "gtin", 14)
            selectors = [
                ("external_id", external_id),
                ("source_name", source_name),
                ("gtin", gtin),
            ]
            selected = [(field, value) for field, value in selectors if value is not None]
            if retailer is None or len(selected) != 1:
                raise ValueError(
                    f"Each member in curated product {key} needs a retailer and exactly one selector"
                )
            field, value = selected[0]
            claim = (retailer.casefold(), field, value.casefold())
            if claim in claimed_members:
                raise ValueError(f"Curated member {retailer}/{field}/{value} is duplicated")
            claimed_members.add(claim)
            members.append(
                MappingMember(
                    retailer=retailer,
                    external_id=external_id,
                    source_name=source_name,
                    gtin=gtin,
                )
            )
        mappings.append(
            ProductMapping(
                key=key,
                name=name,
                category=_optional_text(item.get("category"), "category", 100),
                unit=_optional_text(item.get("unit"), "unit", 20),
                members=tuple(members),
            )
        )
    return tuple(mappings)


def _matching_source_products(db: Session, mapping: ProductMapping) -> list[RetailerProduct]:
    matches: dict[int, RetailerProduct] = {}
    for member in mapping.members:
        query = (
            select(RetailerProduct)
            .join(Trgovina)
            .where(func.lower(Trgovina.ime) == member.retailer.casefold())
        )
        if member.external_id is not None:
            query = query.where(RetailerProduct.external_id == member.external_id)
        elif member.source_name is not None:
            query = query.where(func.lower(RetailerProduct.ime) == member.source_name.casefold())
        else:
            query = query.where(RetailerProduct.gtin == member.gtin)
        for source in db.scalars(query):
            matches[source.id] = source
    return list(matches.values())


def _merge_prices(db: Session, target_id: int, source_ids: set[int]) -> None:
    target_prices = {
        (price.trgovina_id, price.datum_zajema): price
        for price in db.scalars(select(Cena).where(Cena.izdelek_id == target_id))
    }
    for price in db.scalars(select(Cena).where(Cena.izdelek_id.in_(source_ids))):
        key = (price.trgovina_id, price.datum_zajema)
        existing = target_prices.get(key)
        if existing is None:
            price.izdelek_id = target_id
            target_prices[key] = price
        else:
            existing.cena = min(existing.cena, price.cena)
            db.delete(price)


def _merge_list_items(db: Session, target_id: int, source_ids: set[int]) -> None:
    target_items = {
        item.seznam_id: item
        for item in db.scalars(select(SeznamIzdelek).where(SeznamIzdelek.izdelek_id == target_id))
    }
    for item in db.scalars(
        select(SeznamIzdelek).where(SeznamIzdelek.izdelek_id.in_(source_ids))
    ):
        existing = target_items.get(item.seznam_id)
        if existing is None:
            item.izdelek_id = target_id
            target_items[item.seznam_id] = item
        else:
            existing.kolicina += item.kolicina
            db.delete(item)


def apply_curated_mappings(
    db: Session,
    mappings: tuple[ProductMapping, ...] | None = None,
) -> dict[int, int]:
    """Merge configured source products and return source-product to canonical IDs."""
    assignments: dict[int, int] = {}
    for mapping in mappings if mappings is not None else load_product_mappings():
        sources = _matching_source_products(db, mapping)
        if not sources:
            continue
        canonical_ids = {source.izdelek_id for source in sources if source.izdelek_id is not None}
        if canonical_ids:
            counts = {
                canonical_id: sum(source.izdelek_id == canonical_id for source in sources)
                for canonical_id in canonical_ids
            }
            target_id = min(canonical_ids, key=lambda value: (-counts[value], value))
            target = db.get(Izdelek, target_id)
            if target is None:
                raise RuntimeError(f"Curated product {mapping.key} references a missing product")
        else:
            target = Izdelek(ime=mapping.name, kategorija=mapping.category, enota=mapping.unit)
            db.add(target)
            db.flush()
            target_id = target.id

        target.ime = mapping.name
        target.kategorija = mapping.category
        target.enota = mapping.unit
        loser_ids = canonical_ids - {target_id}
        if loser_ids:
            _merge_prices(db, target_id, loser_ids)
            _merge_list_items(db, target_id, loser_ids)
            for source in db.scalars(
                select(RetailerProduct).where(RetailerProduct.izdelek_id.in_(loser_ids))
            ):
                source.izdelek_id = target_id
            for alias in db.scalars(select(ProductGtin).where(ProductGtin.izdelek_id.in_(loser_ids))):
                alias.izdelek_id = target_id
            db.flush()
            for loser_id in loser_ids:
                loser = db.get(Izdelek, loser_id)
                if loser is not None:
                    db.delete(loser)

        for source in sources:
            source.izdelek_id = target_id
            assignments[source.id] = target_id
        db.flush()
    return assignments
