"""Synchronize and backfill the catalog taxonomy in one transaction."""

from sqlalchemy import func, select

from .database import SessionLocal
from .models import Category, Izdelek
from .taxonomy import classify_products, sync_taxonomy


def main() -> None:
    with SessionLocal.begin() as db:
        categories = sync_taxonomy(db)
        stats = classify_products(db, categories_by_slug=categories)
        counts = list(
            db.execute(
                select(Category.slug, func.count(Izdelek.id))
                .outerjoin(Izdelek, Izdelek.category_id == Category.id)
                .group_by(Category.id, Category.slug)
                .having(func.count(Izdelek.id) > 0)
                .order_by(Category.slug)
            )
        )
    print(
        f"Taxonomy: {len(categories)} categories; {stats.classified}/{stats.total} classified "
        f"({stats.visible} visible, {stats.hidden} hidden, {stats.unclassified} unclassified); "
        f"{stats.changed} assignments changed"
    )
    if counts:
        print("Counts: " + ", ".join(f"{slug}={count}" for slug, count in counts))


if __name__ == "__main__":
    main()
