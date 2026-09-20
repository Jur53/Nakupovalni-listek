"""One-shot catalog importer intended for an external daily scheduler."""

import argparse
import logging

from .catalog_import import run_import
from .database import SessionLocal, engine
from .scraper_mercator import MercatorAdapter
from .scraper_hofer import HoferAdapter
from .scraper_lidl import LidlAdapter
from .scraper_spar import SparAdapter
from .scraper_tus import TusAdapter


ADAPTERS = {
    "mercator": MercatorAdapter,
    "spar": SparAdapter,
    "lidl": LidlAdapter,
    "hofer": HoferAdapter,
    "tus": TusAdapter,
}


def main():
    parser = argparse.ArgumentParser(description="Import retailer catalogs and daily prices")
    parser.add_argument("--retailer", choices=["all", *ADAPTERS], default="all")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    names = list(ADAPTERS) if args.retailer == "all" else [args.retailer]
    failed = False
    for name in names:
        try:
            result = run_import(ADAPTERS[name](), SessionLocal, engine)
            print(
                f"{result.retailer}: {result.status}; "
                f"{result.products_seen} products, {result.products_mapped} mapped, "
                f"{result.snapshots_written} snapshots, {result.prices_written} prices"
            )
        except Exception:
            logging.exception("%s catalog import failed", name)
            failed = True
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
