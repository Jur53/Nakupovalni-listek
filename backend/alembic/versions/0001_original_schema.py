"""Baseline the original anonymous-list schema.

Revision ID: 0001_original
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_original"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trgovine",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ime", sa.String(100), nullable=False),
        sa.UniqueConstraint("ime", name="uq_trgovine_ime"),
    )
    op.create_table(
        "izdelki",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ime", sa.String(200), nullable=False),
        sa.Column("kategorija", sa.String(100)),
        sa.Column("enota", sa.String(20)),
    )
    op.create_table(
        "cene",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("izdelek_id", sa.Integer(), sa.ForeignKey("izdelki.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trgovina_id", sa.Integer(), sa.ForeignKey("trgovine.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cena", sa.Numeric(6, 2), nullable=False),
        sa.Column("datum_zajema", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=False),
        sa.UniqueConstraint(
            "izdelek_id",
            "trgovina_id",
            "datum_zajema",
            name="cene_izdelek_id_trgovina_id_datum_zajema_key",
        ),
    )
    op.create_table(
        "seznami",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ime", sa.String(100)),
        sa.Column("ustvarjen", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "seznam_izdelki",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("seznam_id", sa.Integer(), sa.ForeignKey("seznami.id", ondelete="CASCADE"), nullable=False),
        sa.Column("izdelek_id", sa.Integer(), sa.ForeignKey("izdelki.id"), nullable=False),
        sa.Column("kolicina", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade():
    op.drop_table("seznam_izdelki")
    op.drop_table("seznami")
    op.drop_table("cene")
    op.drop_table("izdelki")
    op.drop_table("trgovine")
