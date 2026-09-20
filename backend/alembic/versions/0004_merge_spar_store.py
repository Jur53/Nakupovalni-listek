"""Merge case-variant SPAR store rows.

Revision ID: 0004_merge_spar_store
Revises: 0003_catalog_imports
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_merge_spar_store"
down_revision = "0003_catalog_imports"
branch_labels = None
depends_on = None


def _merge_retailer_product(connection, target, source):
    target_id = target["id"]
    source_id = source["id"]
    target_gtins = set(
        connection.scalars(
            sa.text(
                "SELECT gtin FROM retailer_product_gtins "
                "WHERE retailer_product_id = :product_id"
            ),
            {"product_id": target_id},
        )
    )
    source_gtins = list(
        connection.scalars(
            sa.text(
                "SELECT gtin FROM retailer_product_gtins "
                "WHERE retailer_product_id = :product_id"
            ),
            {"product_id": source_id},
        )
    )
    gtin_table = sa.table(
        "retailer_product_gtins",
        sa.column("retailer_product_id", sa.Integer()),
        sa.column("gtin", sa.String()),
    )
    for gtin in source_gtins:
        if gtin not in target_gtins:
            connection.execute(
                gtin_table.insert().values(retailer_product_id=target_id, gtin=gtin)
            )
            target_gtins.add(gtin)
    connection.execute(
        sa.text("DELETE FROM retailer_product_gtins WHERE retailer_product_id = :source_id"),
        {"source_id": source_id},
    )

    snapshot_table = sa.table(
        "retailer_price_snapshots",
        sa.column("id", sa.Integer()),
        sa.column("retailer_product_id", sa.Integer()),
        sa.column("captured_on", sa.Date()),
        sa.column("captured_at", sa.DateTime()),
        sa.column("effective_price", sa.Numeric()),
        sa.column("regular_price", sa.Numeric()),
        sa.column("promotion_price", sa.Numeric()),
        sa.column("previous_price", sa.Numeric()),
        sa.column("lowest_30d_price", sa.Numeric()),
        sa.column("unit_price", sa.Numeric()),
        sa.column("unit_base", sa.String()),
        sa.column("currency", sa.String()),
        sa.column("promotion_type", sa.String()),
        sa.column("promotion_starts_at", sa.DateTime()),
        sa.column("promotion_ends_at", sa.DateTime()),
        sa.column("requires_loyalty", sa.Boolean()),
        sa.column("promotion_data", sa.JSON()),
    )
    target_snapshots = {
        row["captured_on"]: row
        for row in connection.execute(
            sa.select(snapshot_table).where(
                snapshot_table.c.retailer_product_id == target_id
            )
        ).mappings()
    }
    snapshot_fields = (
        "captured_at",
        "effective_price",
        "regular_price",
        "promotion_price",
        "previous_price",
        "lowest_30d_price",
        "unit_price",
        "unit_base",
        "currency",
        "promotion_type",
        "promotion_starts_at",
        "promotion_ends_at",
        "requires_loyalty",
        "promotion_data",
    )
    for snapshot in connection.execute(
        sa.select(snapshot_table)
        .where(snapshot_table.c.retailer_product_id == source_id)
        .order_by(snapshot_table.c.id)
    ).mappings():
        existing = target_snapshots.get(snapshot["captured_on"])
        if existing is None:
            connection.execute(
                sa.text(
                    "UPDATE retailer_price_snapshots SET retailer_product_id = :target_id "
                    "WHERE id = :snapshot_id"
                ),
                {"target_id": target_id, "snapshot_id": snapshot["id"]},
            )
            continue
        if snapshot["captured_at"] >= existing["captured_at"]:
            values = {field: snapshot[field] for field in snapshot_fields}
            connection.execute(
                snapshot_table.update()
                .where(snapshot_table.c.id == existing["id"])
                .values(**values)
            )
        connection.execute(
            sa.text("DELETE FROM retailer_price_snapshots WHERE id = :snapshot_id"),
            {"snapshot_id": snapshot["id"]},
        )

    source_is_newer = source["last_seen_at"] > target["last_seen_at"]
    preferred, fallback = (source, target) if source_is_newer else (target, source)
    target_canonical = target["izdelek_id"]
    source_canonical = source["izdelek_id"]
    canonical_id = (
        None
        if target_canonical is not None
        and source_canonical is not None
        and target_canonical != source_canonical
        else target_canonical or source_canonical
    )
    text_fields = ("ime", "gtin", "brand", "kategorija", "enota", "url", "image_url")
    values = {
        field: preferred[field] or fallback[field]
        for field in text_fields
    }
    values.update(
        {
            "product_id": target_id,
            "izdelek_id": canonical_id,
            "is_active": bool(target["is_active"] or source["is_active"]),
            "first_seen_at": min(target["first_seen_at"], source["first_seen_at"]),
            "last_seen_at": max(target["last_seen_at"], source["last_seen_at"]),
            "last_seen_run_id": (
                preferred["last_seen_run_id"] or fallback["last_seen_run_id"]
            ),
        }
    )
    assignments = ", ".join(
        f"{field} = :{field}"
        for field in (*text_fields, "izdelek_id", "is_active", "first_seen_at", "last_seen_at", "last_seen_run_id")
    )
    connection.execute(
        sa.text(f"UPDATE retailer_products SET {assignments} WHERE id = :product_id"),
        values,
    )
    connection.execute(
        sa.text("DELETE FROM retailer_products WHERE id = :source_id"),
        {"source_id": source_id},
    )


def upgrade():
    connection = op.get_bind()
    target_id = connection.scalar(sa.text("SELECT id FROM trgovine WHERE ime = 'SPAR'"))
    duplicate_ids = list(
        connection.scalars(
            sa.text("SELECT id FROM trgovine WHERE lower(ime) = 'spar' ORDER BY id")
        )
    )
    if not duplicate_ids:
        return
    if target_id is None:
        target_id = duplicate_ids.pop(0)
        connection.execute(
            sa.text("UPDATE trgovine SET ime = 'SPAR' WHERE id = :target_id"),
            {"target_id": target_id},
        )
    else:
        duplicate_ids = [store_id for store_id in duplicate_ids if store_id != target_id]

    for source_id in duplicate_ids:
        for price in connection.execute(
            sa.text(
                "SELECT id, izdelek_id, datum_zajema, cena "
                "FROM cene WHERE trgovina_id = :source_id"
            ),
            {"source_id": source_id},
        ).mappings():
            existing = connection.execute(
                sa.text(
                    "SELECT id, cena FROM cene WHERE trgovina_id = :target_id "
                    "AND izdelek_id = :izdelek_id AND datum_zajema = :captured_on"
                ),
                {
                    "target_id": target_id,
                    "izdelek_id": price["izdelek_id"],
                    "captured_on": price["datum_zajema"],
                },
            ).mappings().first()
            if existing is not None:
                if price["cena"] < existing["cena"]:
                    connection.execute(
                        sa.text("UPDATE cene SET cena = :cena WHERE id = :price_id"),
                        {"cena": price["cena"], "price_id": existing["id"]},
                    )
                connection.execute(
                    sa.text("DELETE FROM cene WHERE id = :price_id"),
                    {"price_id": price["id"]},
                )
        connection.execute(
            sa.text("UPDATE cene SET trgovina_id = :target_id WHERE trgovina_id = :source_id"),
            {"source_id": source_id, "target_id": target_id},
        )
        source_products = list(
            connection.execute(
                sa.text("SELECT * FROM retailer_products WHERE trgovina_id = :source_id ORDER BY id"),
                {"source_id": source_id},
            ).mappings()
        )
        for source_product in source_products:
            target_product = connection.execute(
                sa.text(
                    "SELECT * FROM retailer_products WHERE trgovina_id = :target_id "
                    "AND external_id = :external_id"
                ),
                {"target_id": target_id, "external_id": source_product["external_id"]},
            ).mappings().first()
            if target_product is not None:
                _merge_retailer_product(connection, target_product, source_product)
        connection.execute(
            sa.text(
                "UPDATE retailer_products SET trgovina_id = :target_id WHERE trgovina_id = :source_id"
            ),
            {"source_id": source_id, "target_id": target_id},
        )
        connection.execute(
            sa.text(
                "UPDATE catalog_import_runs SET trgovina_id = :target_id WHERE trgovina_id = :source_id"
            ),
            {"source_id": source_id, "target_id": target_id},
        )
        connection.execute(
            sa.text("DELETE FROM trgovine WHERE id = :source_id"),
            {"source_id": source_id},
        )


def downgrade():
    # Store identity merges cannot be reversed without inventing row ownership.
    pass
