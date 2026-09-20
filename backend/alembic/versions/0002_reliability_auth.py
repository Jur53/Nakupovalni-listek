"""Add authentication, ownership, constraints, and retailer mappings.

Revision ID: 0002_reliability
Revises: 0001_original
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_reliability"
down_revision = "0001_original"
branch_labels = None
depends_on = None


LATEST_PRICE_VIEW = """
CREATE VIEW zadnje_cene AS
SELECT DISTINCT ON (izdelek_id, trgovina_id)
    izdelek_id, trgovina_id, cena, datum_zajema
FROM cene
ORDER BY izdelek_id, trgovina_id, datum_zajema DESC
"""


def drop_postgresql_latest_price_view():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP VIEW IF EXISTS zadnje_cene")


def create_postgresql_latest_price_view():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(LATEST_PRICE_VIEW)


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_legacy", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    connection = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.Integer()),
        sa.column("email", sa.String()),
        sa.column("password_hash", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_legacy", sa.Boolean()),
    )
    connection.execute(
        users.insert().values(
            email="legacy-disabled@invalid.local",
            password_hash="!locked-no-password!",
            is_active=False,
            is_legacy=True,
        )
    )
    legacy_id = connection.scalar(sa.select(users.c.id).where(users.c.email == "legacy-disabled@invalid.local"))

    with op.batch_alter_table("seznami") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
    connection.execute(sa.text("UPDATE seznami SET user_id = :user_id"), {"user_id": legacy_id})
    connection.execute(sa.text("UPDATE seznami SET ime = 'Legacy list ' || id WHERE ime IS NULL OR trim(ime) = ''"))

    # Normalize bad quantities and merge duplicate list/product rows before constraints.
    rows = connection.execute(
        sa.text("SELECT id, seznam_id, izdelek_id, kolicina FROM seznam_izdelki ORDER BY id")
    ).mappings()
    grouped = {}
    for row in rows:
        key = (row["seznam_id"], row["izdelek_id"])
        quantity = row["kolicina"] if row["kolicina"] and row["kolicina"] > 0 else 1
        if key not in grouped:
            grouped[key] = [row["id"], quantity]
        else:
            grouped[key][1] += quantity
            connection.execute(sa.text("DELETE FROM seznam_izdelki WHERE id = :id"), {"id": row["id"]})
    for keeper_id, quantity in grouped.values():
        connection.execute(
            sa.text("UPDATE seznam_izdelki SET kolicina = :quantity WHERE id = :id"),
            {"quantity": quantity, "id": keeper_id},
        )
    cleaned_items = [
        {
            "id": keeper_id,
            "seznam_id": seznam_id,
            "izdelek_id": izdelek_id,
            "kolicina": quantity,
        }
        for (seznam_id, izdelek_id), (keeper_id, quantity) in grouped.items()
    ]
    connection.execute(sa.text("UPDATE cene SET cena = 0 WHERE cena < 0"))

    with op.batch_alter_table("seznami") as batch:
        batch.alter_column("user_id", nullable=False)
        batch.alter_column("ime", existing_type=sa.String(100), nullable=False)
        batch.create_foreign_key("fk_seznami_user", "users", ["user_id"], ["id"], ondelete="CASCADE")

    # SQLite's table-copy implementation can fire the old list cascade while
    # rebuilding seznami. Restore only rows that the rebuild removed.
    list_items = sa.table(
        "seznam_izdelki",
        sa.column("id", sa.Integer()),
        sa.column("seznam_id", sa.Integer()),
        sa.column("izdelek_id", sa.Integer()),
        sa.column("kolicina", sa.Integer()),
    )
    existing_item_ids = set(connection.scalars(sa.select(list_items.c.id)))
    missing_items = [item for item in cleaned_items if item["id"] not in existing_item_ids]
    if missing_items:
        connection.execute(list_items.insert(), missing_items)

    with op.batch_alter_table("seznam_izdelki") as batch:
        batch.create_check_constraint("ck_seznam_izdelki_positive_quantity", "kolicina > 0")
        batch.create_unique_constraint("uq_seznam_product", ["seznam_id", "izdelek_id"])
    drop_postgresql_latest_price_view()
    with op.batch_alter_table("cene") as batch:
        batch.alter_column("cena", existing_type=sa.Numeric(6, 2), type_=sa.Numeric(12, 2), nullable=False)
        batch.create_check_constraint("ck_cene_nonnegative", "cena >= 0")
    create_postgresql_latest_price_view()

    op.create_index("ix_izdelki_ime", "izdelki", ["ime"])
    op.create_index("ix_cene_product_store_date", "cene", ["izdelek_id", "trgovina_id", "datum_zajema"])
    op.create_index("ix_seznami_user_created", "seznami", ["user_id", "ustvarjen", "id"])
    op.create_index("ix_seznam_izdelki_product", "seznam_izdelki", ["izdelek_id"])
    op.create_table(
        "retailer_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trgovina_id", sa.Integer(), sa.ForeignKey("trgovine.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("ime", sa.String(300), nullable=False),
        sa.Column("gtin", sa.String(32)),
        sa.Column("url", sa.String(1000)),
        sa.Column("izdelek_id", sa.Integer(), sa.ForeignKey("izdelki.id", ondelete="SET NULL")),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("trgovina_id", "external_id", name="uq_retailer_product_external"),
    )
    op.create_index("ix_retailer_products_canonical", "retailer_products", ["izdelek_id"])


def downgrade():
    op.drop_index("ix_retailer_products_canonical", table_name="retailer_products")
    op.drop_table("retailer_products")
    op.drop_index("ix_seznam_izdelki_product", table_name="seznam_izdelki")
    op.drop_index("ix_seznami_user_created", table_name="seznami")
    op.drop_index("ix_cene_product_store_date", table_name="cene")
    op.drop_index("ix_izdelki_ime", table_name="izdelki")
    drop_postgresql_latest_price_view()
    with op.batch_alter_table("cene") as batch:
        batch.drop_constraint("ck_cene_nonnegative", type_="check")
        batch.alter_column("cena", existing_type=sa.Numeric(12, 2), type_=sa.Numeric(6, 2))
    create_postgresql_latest_price_view()
    with op.batch_alter_table("seznam_izdelki") as batch:
        batch.drop_constraint("uq_seznam_product", type_="unique")
        batch.drop_constraint("ck_seznam_izdelki_positive_quantity", type_="check")
    with op.batch_alter_table("seznami") as batch:
        batch.drop_constraint("fk_seznami_user", type_="foreignkey")
        batch.drop_column("user_id")
        batch.alter_column("ime", existing_type=sa.String(100), nullable=True)
    op.drop_table("users")
