"""Add extensible retailer catalog imports and price observations.

Revision ID: 0003_catalog_imports
Revises: 0002_reliability
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_catalog_imports"
down_revision = "0002_reliability"
branch_labels = None
depends_on = None


def _normalize_gtin(value):
    gtin = str(value).strip() if value is not None else ""
    if len(gtin) not in {8, 12, 13, 14} or not gtin.isdigit():
        return None
    total = sum(
        int(digit) * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(gtin[:-1]))
    )
    return gtin if (10 - total % 10) % 10 == int(gtin[-1]) else None


def upgrade():
    op.create_index("ix_izdelki_category_name", "izdelki", ["kategorija", "ime"])
    op.create_table(
        "product_gtins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("izdelek_id", sa.Integer(), sa.ForeignKey("izdelki.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gtin", sa.String(14), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("gtin", name="uq_product_gtins_gtin"),
    )
    connection = op.get_bind()
    legacy_gtins = list(
        connection.execute(
            sa.text(
                "SELECT id, izdelek_id, gtin FROM retailer_products "
                "WHERE gtin IS NOT NULL ORDER BY id"
            )
        ).mappings()
    )
    aliases = sa.table(
        "product_gtins",
        sa.column("izdelek_id", sa.Integer()),
        sa.column("gtin", sa.String()),
    )
    canonical_ids_by_gtin = {}
    for row in legacy_gtins:
        gtin = _normalize_gtin(row["gtin"])
        if gtin and row["izdelek_id"] is not None:
            canonical_ids_by_gtin.setdefault(gtin, set()).add(row["izdelek_id"])
    for gtin, canonical_ids in canonical_ids_by_gtin.items():
        if len(canonical_ids) == 1:
            connection.execute(
                aliases.insert().values(izdelek_id=next(iter(canonical_ids)), gtin=gtin)
            )
    op.create_table(
        "catalog_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trgovina_id", sa.Integer(), sa.ForeignKey("trgovine.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("captured_on", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("products_seen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("products_mapped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("snapshots_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prices_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'skipped')",
            name="ck_catalog_import_runs_status",
        ),
    )
    op.create_index(
        "ix_catalog_import_runs_store_date",
        "catalog_import_runs",
        ["trgovina_id", "captured_on", "id"],
    )

    with op.batch_alter_table("retailer_products") as batch:
        batch.add_column(sa.Column("brand", sa.String(200)))
        batch.add_column(sa.Column("kategorija", sa.String(300)))
        batch.add_column(sa.Column("enota", sa.String(50)))
        batch.add_column(sa.Column("image_url", sa.String(1000)))
        batch.add_column(sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))
        batch.add_column(sa.Column("first_seen_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
        batch.add_column(sa.Column("last_seen_run_id", sa.Integer()))
        batch.create_foreign_key(
            "fk_retailer_products_last_seen_run",
            "catalog_import_runs",
            ["last_seen_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_retailer_products_store_active", ["trgovina_id", "is_active"])

    op.create_table(
        "retailer_product_gtins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "retailer_product_id",
            sa.Integer(),
            sa.ForeignKey("retailer_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gtin", sa.String(14), nullable=False),
        sa.UniqueConstraint("retailer_product_id", "gtin", name="uq_retailer_product_gtin"),
    )
    op.create_index("ix_retailer_product_gtins_gtin", "retailer_product_gtins", ["gtin"])
    source_aliases = sa.table(
        "retailer_product_gtins",
        sa.column("retailer_product_id", sa.Integer()),
        sa.column("gtin", sa.String()),
    )
    for row in legacy_gtins:
        gtin = _normalize_gtin(row["gtin"])
        if gtin:
            connection.execute(
                source_aliases.insert().values(
                    retailer_product_id=row["id"],
                    gtin=gtin,
                )
            )

    op.create_table(
        "retailer_price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "retailer_product_id",
            sa.Integer(),
            sa.ForeignKey("retailer_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("captured_on", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("effective_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("regular_price", sa.Numeric(12, 2)),
        sa.Column("promotion_price", sa.Numeric(12, 2)),
        sa.Column("previous_price", sa.Numeric(12, 2)),
        sa.Column("lowest_30d_price", sa.Numeric(12, 2)),
        sa.Column("unit_price", sa.Numeric(14, 4)),
        sa.Column("unit_base", sa.String(50)),
        sa.Column("currency", sa.String(3), server_default="EUR", nullable=False),
        sa.Column("promotion_type", sa.String(100)),
        sa.Column("promotion_starts_at", sa.DateTime()),
        sa.Column("promotion_ends_at", sa.DateTime()),
        sa.Column("requires_loyalty", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("promotion_data", sa.JSON()),
        sa.CheckConstraint("effective_price >= 0", name="ck_retailer_snapshots_effective_nonnegative"),
        sa.UniqueConstraint(
            "retailer_product_id", "captured_on", name="uq_retailer_snapshot_product_date"
        ),
    )
    op.create_index(
        "ix_retailer_snapshots_date",
        "retailer_price_snapshots",
        ["captured_on", "retailer_product_id"],
    )


def downgrade():
    op.drop_index("ix_retailer_snapshots_date", table_name="retailer_price_snapshots")
    op.drop_table("retailer_price_snapshots")
    op.drop_index("ix_retailer_product_gtins_gtin", table_name="retailer_product_gtins")
    op.drop_table("retailer_product_gtins")
    with op.batch_alter_table("retailer_products") as batch:
        batch.drop_index("ix_retailer_products_store_active")
        batch.drop_constraint("fk_retailer_products_last_seen_run", type_="foreignkey")
        batch.drop_column("last_seen_run_id")
        batch.drop_column("first_seen_at")
        batch.drop_column("is_active")
        batch.drop_column("image_url")
        batch.drop_column("enota")
        batch.drop_column("kategorija")
        batch.drop_column("brand")
    op.drop_index("ix_catalog_import_runs_store_date", table_name="catalog_import_runs")
    op.drop_table("catalog_import_runs")
    op.drop_table("product_gtins")
    op.drop_index("ix_izdelki_category_name", table_name="izdelki")
