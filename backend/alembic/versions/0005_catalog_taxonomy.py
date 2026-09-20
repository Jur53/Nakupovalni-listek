"""Add the stable shopper catalog taxonomy.

Revision ID: 0005_catalog_taxonomy
Revises: 0004_merge_spar_store
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_catalog_taxonomy"
down_revision = "0004_merge_spar_store"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_index(
        "ix_categories_parent_sort", "categories", ["parent_id", "sort_order", "id"]
    )
    with op.batch_alter_table("izdelki") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_izdelki_category_id_categories",
            "categories",
            ["category_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_izdelki_category_id", ["category_id"])


def downgrade():
    with op.batch_alter_table("izdelki") as batch_op:
        batch_op.drop_index("ix_izdelki_category_id")
        batch_op.drop_constraint("fk_izdelki_category_id_categories", type_="foreignkey")
        batch_op.drop_column("category_id")
    # SQLite enforces the self-referential RESTRICT constraint during DROP TABLE.
    op.execute(sa.text("UPDATE categories SET parent_id = NULL"))
    op.drop_index("ix_categories_parent_sort", table_name="categories")
    op.drop_table("categories")
