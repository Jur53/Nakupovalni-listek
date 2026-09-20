"""Validated taxonomy definitions, synchronization, and deterministic classification."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Category, Izdelek, RetailerProduct


TAXONOMY_PATH = Path(__file__).with_name("catalog_taxonomy.json")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NON_CATEGORY_SLUGS = {"sale", "special-offer", "bio", "vegan", "gluten-free"}


def normalize_taxonomy_text(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.sub(r"[^\w]+", " ", ascii_text.casefold()).split())


@dataclass(frozen=True)
class CategoryDefinition:
    slug: str
    name: str
    parent_slug: str | None
    sort_order: int
    is_visible: bool


@dataclass(frozen=True)
class ClassificationRule:
    category_slug: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomyDefinition:
    categories: tuple[CategoryDefinition, ...]
    source_category_rules: tuple[ClassificationRule, ...]
    product_name_rules: tuple[ClassificationRule, ...]
    fallback_source_category_rules: tuple[ClassificationRule, ...]


@dataclass(frozen=True)
class ClassificationStats:
    total: int
    classified: int
    visible: int
    hidden: int
    unclassified: int
    changed: int


def _category_definitions(raw_categories: object) -> tuple[CategoryDefinition, ...]:
    if not isinstance(raw_categories, list) or not raw_categories:
        raise ValueError("Taxonomy categories must be a non-empty array")
    definitions: list[CategoryDefinition] = []
    slugs: set[str] = set()

    def visit(items: object, parent_slug: str | None, parent_visible: bool) -> None:
        if not isinstance(items, list):
            raise ValueError("Category children must be an array")
        for position, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError("Each taxonomy category must be an object")
            slug = item.get("slug")
            name = item.get("name")
            visible = item.get("is_visible", True)
            sort_order = item.get("sort_order", (position + 1) * 10)
            if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or len(slug) > 100:
                raise ValueError(f"Invalid taxonomy category slug: {slug!r}")
            if slug in slugs:
                raise ValueError(f"Duplicate taxonomy category slug: {slug}")
            if slug in NON_CATEGORY_SLUGS:
                raise ValueError(f"Promotional or attribute concept cannot be a category: {slug}")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
                raise ValueError(f"Invalid name for taxonomy category {slug}")
            if not isinstance(visible, bool) or not isinstance(sort_order, int) or sort_order < 0:
                raise ValueError(f"Invalid metadata for taxonomy category {slug}")
            if visible and not parent_visible:
                raise ValueError(f"Visible category {slug} cannot have a hidden parent")
            slugs.add(slug)
            definitions.append(
                CategoryDefinition(slug, name.strip(), parent_slug, sort_order, visible)
            )
            visit(item.get("children", []), slug, visible)

    visit(raw_categories, None, True)
    return tuple(definitions)


def _classification_rules(
    raw_rules: object,
    field: str,
    category_slugs: set[str],
) -> tuple[ClassificationRule, ...]:
    if not isinstance(raw_rules, list):
        raise ValueError(f"Taxonomy {field} must be an array")
    result: list[ClassificationRule] = []
    claimed_keywords: dict[str, str] = {}
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Each {field} entry must be an object")
        category_slug = raw_rule.get("category")
        keywords = raw_rule.get("keywords")
        if category_slug not in category_slugs:
            raise ValueError(f"Unknown taxonomy rule category: {category_slug!r}")
        if not isinstance(keywords, list) or not keywords:
            raise ValueError(f"Taxonomy rule {category_slug} must have keywords")
        normalized_keywords: list[str] = []
        for keyword in keywords:
            normalized = normalize_taxonomy_text(keyword) if isinstance(keyword, str) else ""
            if not normalized:
                raise ValueError(f"Invalid keyword in taxonomy rule {category_slug}")
            previous = claimed_keywords.get(normalized)
            if previous is not None and previous != category_slug:
                raise ValueError(
                    f"Ambiguous normalized keyword {normalized!r} targets {previous} and {category_slug}"
                )
            claimed_keywords[normalized] = category_slug
            if normalized not in normalized_keywords:
                normalized_keywords.append(normalized)
        result.append(ClassificationRule(category_slug, tuple(normalized_keywords)))
    return tuple(result)


@lru_cache
def load_taxonomy(path: Path = TAXONOMY_PATH) -> TaxonomyDefinition:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("Taxonomy must be an object with version 1")
    categories = _category_definitions(raw.get("categories"))
    slugs = {category.slug for category in categories}
    return TaxonomyDefinition(
        categories=categories,
        source_category_rules=_classification_rules(
            raw.get("source_category_rules"), "source_category_rules", slugs
        ),
        product_name_rules=_classification_rules(
            raw.get("product_name_rules"), "product_name_rules", slugs
        ),
        fallback_source_category_rules=_classification_rules(
            raw.get("fallback_source_category_rules", []),
            "fallback_source_category_rules",
            slugs,
        ),
    )


def sync_taxonomy(
    db: Session,
    definition: TaxonomyDefinition | None = None,
) -> dict[str, Category]:
    """Upsert checked-in categories without deleting database-only rows."""
    definition = definition or load_taxonomy()
    by_slug = {category.slug: category for category in db.scalars(select(Category))}
    for item in definition.categories:
        category = by_slug.get(item.slug)
        if category is None:
            category = Category(slug=item.slug, name=item.name)
            db.add(category)
            db.flush()
            by_slug[item.slug] = category
        category.name = item.name
        category.parent_id = by_slug[item.parent_slug].id if item.parent_slug else None
        category.sort_order = item.sort_order
        category.is_visible = item.is_visible
    db.flush()
    return by_slug


def _rule_match(texts: list[str], rules: tuple[ClassificationRule, ...]) -> str | None:
    padded = [f" {normalize_taxonomy_text(text)} " for text in texts if text]
    for rule in rules:
        for keyword in rule.keywords:
            needle = f" {keyword} "
            if any(needle in text for text in padded):
                return rule.category_slug
    return None


def _ranked_source_matches(
    texts: list[str], rules: tuple[ClassificationRule, ...]
) -> list[str]:
    """Return source matches with longer, more specific phrases first."""
    padded = [f" {normalize_taxonomy_text(text)} " for text in texts if text]
    matches: list[tuple[int, int, int, str]] = []
    for position, rule in enumerate(rules):
        matching_keywords = [
            keyword
            for keyword in rule.keywords
            if any(f" {keyword} " in text for text in padded)
        ]
        if matching_keywords:
            best = max(matching_keywords, key=lambda keyword: (len(keyword.split()), len(keyword)))
            matches.append((-len(best.split()), -len(best), position, rule.category_slug))
    return [category_slug for _, _, _, category_slug in sorted(matches)]


def classify_products(
    db: Session,
    product_ids: set[int] | list[int] | tuple[int, ...] | None = None,
    definition: TaxonomyDefinition | None = None,
    categories_by_slug: dict[str, Category] | None = None,
) -> ClassificationStats:
    """Classify only the requested canonical IDs, or every product for a backfill."""
    definition = definition or load_taxonomy()
    categories_by_slug = categories_by_slug or sync_taxonomy(db, definition)
    product_query = select(Izdelek).order_by(Izdelek.id)
    normalized_ids = None if product_ids is None else sorted(set(product_ids))
    if normalized_ids is not None:
        if not normalized_ids:
            return ClassificationStats(0, 0, 0, 0, 0, 0)
        product_query = product_query.where(Izdelek.id.in_(normalized_ids))
    db.flush()
    products = list(db.scalars(product_query))
    ids = [product.id for product in products]
    source_categories: dict[int, list[tuple[bool, str]]] = {
        product_id: [] for product_id in ids
    }
    if ids:
        for canonical_id, is_active, source_category in db.execute(
            select(
                RetailerProduct.izdelek_id,
                RetailerProduct.is_active,
                RetailerProduct.kategorija,
            )
            .where(
                RetailerProduct.izdelek_id.in_(ids),
                RetailerProduct.kategorija.is_not(None),
            )
            .order_by(RetailerProduct.izdelek_id, RetailerProduct.id)
        ):
            source_categories[canonical_id].append((is_active, source_category))

    changed = 0
    visible = 0
    hidden = 0
    unclassified = 0
    definitions_by_slug = {item.slug: item for item in definition.categories}

    def is_descendant(slug: str, ancestor_slug: str) -> bool:
        seen: set[str] = set()
        current = definitions_by_slug.get(slug)
        while current is not None and current.slug not in seen:
            if current.parent_slug == ancestor_slug:
                return True
            seen.add(current.slug)
            current = definitions_by_slug.get(current.parent_slug) if current.parent_slug else None
        return False

    for product in products:
        # An explicit taxonomy slug wins. Source categories choose a branch, while
        # product names may safely refine that branch to a descendant.
        direct_slug = (product.kategorija or "").strip().casefold()
        slug = direct_slug if direct_slug in categories_by_slug else None
        if slug is None:
            source_values = source_categories.get(product.id, [])
            active_values = [value for active, value in source_values if active]
            source_texts = [product.kategorija or ""] + (
                active_values or [value for _, value in source_values]
            )
            source_slugs = _ranked_source_matches(
                source_texts, definition.source_category_rules
            )
            source_slug = source_slugs[0] if source_slugs else None
            name_slug = _rule_match([product.ime], definition.product_name_rules)
            fallback_slug = _rule_match(
                source_texts,
                definition.fallback_source_category_rules,
            )
            if source_slug and name_slug and any(
                name_slug == candidate or is_descendant(name_slug, candidate)
                for candidate in source_slugs
            ):
                slug = name_slug
            else:
                slug = source_slug or name_slug or fallback_slug
        category = categories_by_slug.get(slug) if slug else None
        new_id = category.id if category else None
        if product.category_id != new_id:
            product.category_id = new_id
            changed += 1
        if category is None:
            unclassified += 1
        elif category.is_visible:
            visible += 1
        else:
            hidden += 1
    db.flush()
    return ClassificationStats(
        total=len(products),
        classified=visible + hidden,
        visible=visible,
        hidden=hidden,
        unclassified=unclassified,
        changed=changed,
    )
