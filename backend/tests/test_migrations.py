from datetime import date, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def alembic_config(connection):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def test_0003_backfills_valid_gtins_from_mapped_retailer_products(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    with engine.begin() as connection:
        config = alembic_config(connection)
        command.upgrade(config, "0002_reliability")
        connection.execute(text("INSERT INTO trgovine (ime) VALUES ('Store')"))
        connection.execute(text("INSERT INTO izdelki (ime) VALUES ('Mapped'), ('Other')"))
        connection.execute(
            text(
                "INSERT INTO retailer_products "
                "(trgovina_id, external_id, ime, gtin, izdelek_id) VALUES "
                "(1, 'one', 'One', '3838975531314', 1), "
                "(1, 'duplicate', 'Duplicate', '3838975531314', 2), "
                "(1, 'invalid', 'Invalid', '3838975531315', 2), "
                "(1, 'unique', 'Unique', '08052575091176', 2)"
            )
        )

        command.upgrade(config, "0003_catalog_imports")

        aliases = connection.execute(
            text("SELECT izdelek_id, gtin FROM product_gtins ORDER BY id")
        ).all()
        assert aliases == [(2, "08052575091176")]
        source_aliases = connection.execute(
            text(
                "SELECT retailer_product_id, gtin FROM retailer_product_gtins "
                "ORDER BY retailer_product_id"
            )
        ).all()
        assert source_aliases == [
            (1, "3838975531314"),
            (2, "3838975531314"),
            (4, "08052575091176"),
        ]


def test_0004_merges_spar_products_gtins_and_snapshots(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'merge.db'}")
    with engine.begin() as connection:
        config = alembic_config(connection)
        command.upgrade(config, "0003_catalog_imports")
        connection.execute(text("INSERT INTO trgovine (id, ime) VALUES (1, 'SPAR'), (2, 'spar')"))
        connection.execute(
            text("INSERT INTO izdelki (id, ime) VALUES (1, 'Canonical'), (2, 'Conflicting')")
        )
        connection.execute(
            text(
                "INSERT INTO retailer_products "
                "(id, trgovina_id, external_id, ime, izdelek_id, is_active, first_seen_at, last_seen_at) "
                "VALUES (10, 1, 'same', 'Old name', NULL, 0, :old, :old), "
                "(20, 2, 'same', 'Fresh name', 1, 1, :new, :new), "
                "(11, 1, 'conflict', 'Target conflict', 1, 1, :old, :old), "
                "(21, 2, 'conflict', 'Source conflict', 2, 1, :new, :new)"
            ),
            {"old": datetime(2026, 9, 1), "new": datetime(2026, 9, 2)},
        )
        connection.execute(
            text(
                "INSERT INTO retailer_product_gtins (retailer_product_id, gtin) VALUES "
                "(10, '3838975531314'), (20, '3838975531314'), (20, '08052575091176'), "
                "(11, '4006381333931'), (21, '5012345678900')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cene (izdelek_id, trgovina_id, cena, datum_zajema) VALUES "
                "(1, 1, 4.00, :day), (1, 2, 3.00, :day)"
            ),
            {"day": date(2026, 9, 1)},
        )
        connection.execute(
            text(
                "INSERT INTO retailer_price_snapshots "
                "(retailer_product_id, captured_on, captured_at, effective_price, currency, requires_loyalty) "
                "VALUES (10, :first_day, :old, 4.00, 'EUR', 0), "
                "(20, :first_day, :new, 3.00, 'EUR', 0), "
                "(20, :second_day, :new, 2.50, 'EUR', 0)"
            ),
            {
                "first_day": date(2026, 9, 1),
                "second_day": date(2026, 9, 2),
                "old": datetime(2026, 9, 1),
                "new": datetime(2026, 9, 2),
            },
        )

        command.upgrade(config, "0004_merge_spar_store")

        stores = connection.execute(text("SELECT id, ime FROM trgovine")).all()
        assert stores == [(1, "SPAR")]
        merged = connection.execute(
            text(
                "SELECT trgovina_id, ime, izdelek_id, is_active "
                "FROM retailer_products WHERE external_id = 'same'"
            )
        ).one()
        assert merged == (1, "Fresh name", 1, 1)
        conflicting = connection.execute(
            text(
                "SELECT trgovina_id, izdelek_id FROM retailer_products "
                "WHERE external_id = 'conflict'"
            )
        ).one()
        assert conflicting == (1, None)
        assert connection.scalar(text("SELECT count(*) FROM retailer_product_gtins")) == 4
        assert str(connection.scalar(text("SELECT cena FROM cene"))) == "3"
        snapshots = connection.execute(
            text(
                "SELECT captured_on, effective_price FROM retailer_price_snapshots "
                "ORDER BY captured_on"
            )
        ).all()
        assert [(str(day), str(price)) for day, price in snapshots] == [
            ("2026-09-01", "3"),
            ("2026-09-02", "2.5"),
        ]


def test_0005_adds_taxonomy_without_rewriting_legacy_categories(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'taxonomy.db'}")
    with engine.begin() as connection:
        config = alembic_config(connection)
        command.upgrade(config, "0004_merge_spar_store")
        connection.execute(
            text("INSERT INTO izdelki (id, ime, kategorija) VALUES (1, 'Milk', 'Legacy dairy')")
        )

        command.upgrade(config, "0005_catalog_taxonomy")

        columns = {column[1] for column in connection.execute(text("PRAGMA table_info(izdelki)"))}
        assert "category_id" in columns
        assert connection.scalar(text("SELECT kategorija FROM izdelki WHERE id = 1")) == "Legacy dairy"
        assert connection.scalar(text("SELECT category_id FROM izdelki WHERE id = 1")) is None
        assert connection.scalar(text("SELECT count(*) FROM categories")) == 0
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005_catalog_taxonomy"
