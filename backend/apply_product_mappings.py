"""Apply curated product mappings to an existing catalog."""

from .database import SessionLocal
from .product_mappings import apply_curated_mappings


def main() -> None:
    with SessionLocal.begin() as db:
        assignments = apply_curated_mappings(db)
    print(f"Applied curated mappings to {len(assignments)} retailer products")


if __name__ == "__main__":
    main()
