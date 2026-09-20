from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    is_legacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    seznami: Mapped[list["Seznam"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Trgovina(Base):
    __tablename__ = "trgovine"

    id: Mapped[int] = mapped_column(primary_key=True)
    ime: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    cene: Mapped[list["Cena"]] = relationship(back_populates="trgovina", cascade="all, delete-orphan")
    retailer_products: Mapped[list["RetailerProduct"]] = relationship(
        back_populates="trgovina", cascade="all, delete-orphan"
    )
    import_runs: Mapped[list["CatalogImportRun"]] = relationship(
        back_populates="trgovina", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (Index("ix_categories_parent_sort", "parent_id", "sort_order", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    parent: Mapped["Category | None"] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    izdelki: Mapped[list["Izdelek"]] = relationship(back_populates="category")


class Izdelek(Base):
    __tablename__ = "izdelki"
    __table_args__ = (
        Index("ix_izdelki_ime", "ime"),
        Index("ix_izdelki_category_name", "kategorija", "ime"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ime: Mapped[str] = mapped_column(String(200), nullable=False)
    kategorija: Mapped[str | None] = mapped_column(String(100))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "categories.id",
            name="fk_izdelki_category_id_categories",
            ondelete="SET NULL",
            use_alter=True,
        ),
        index=True,
    )
    enota: Mapped[str | None] = mapped_column(String(20))

    category: Mapped[Category | None] = relationship(back_populates="izdelki")
    cene: Mapped[list["Cena"]] = relationship(back_populates="izdelek", cascade="all, delete-orphan")
    gtins: Mapped[list["ProductGtin"]] = relationship(
        back_populates="izdelek", cascade="all, delete-orphan"
    )


class Cena(Base):
    __tablename__ = "cene"
    __table_args__ = (
        CheckConstraint("cena >= 0", name="ck_cene_nonnegative"),
        UniqueConstraint(
            "izdelek_id",
            "trgovina_id",
            "datum_zajema",
            name="cene_izdelek_id_trgovina_id_datum_zajema_key",
        ),
        Index("ix_cene_product_store_date", "izdelek_id", "trgovina_id", "datum_zajema"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    izdelek_id: Mapped[int] = mapped_column(ForeignKey("izdelki.id", ondelete="CASCADE"), nullable=False)
    trgovina_id: Mapped[int] = mapped_column(ForeignKey("trgovine.id", ondelete="CASCADE"), nullable=False)
    cena: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    datum_zajema: Mapped[date] = mapped_column(Date, nullable=False, default=date.today, server_default=func.current_date())

    izdelek: Mapped[Izdelek] = relationship(back_populates="cene")
    trgovina: Mapped[Trgovina] = relationship(back_populates="cene")


class Seznam(Base):
    __tablename__ = "seznami"
    __table_args__ = (Index("ix_seznami_user_created", "user_id", "ustvarjen", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ime: Mapped[str] = mapped_column(String(100), nullable=False)
    ustvarjen: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="seznami")
    izdelki: Mapped[list["SeznamIzdelek"]] = relationship(
        back_populates="seznam", cascade="all, delete-orphan", order_by="SeznamIzdelek.id"
    )


class SeznamIzdelek(Base):
    __tablename__ = "seznam_izdelki"
    __table_args__ = (
        CheckConstraint("kolicina > 0", name="ck_seznam_izdelki_positive_quantity"),
        UniqueConstraint("seznam_id", "izdelek_id", name="uq_seznam_product"),
        Index("ix_seznam_izdelki_product", "izdelek_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    seznam_id: Mapped[int] = mapped_column(ForeignKey("seznami.id", ondelete="CASCADE"), nullable=False)
    # The database default NO ACTION prevents deleting products still on a list.
    izdelek_id: Mapped[int] = mapped_column(ForeignKey("izdelki.id"), nullable=False)
    kolicina: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    seznam: Mapped[Seznam] = relationship(back_populates="izdelki")
    izdelek: Mapped[Izdelek] = relationship()


class RetailerProduct(Base):
    __tablename__ = "retailer_products"
    __table_args__ = (
        UniqueConstraint("trgovina_id", "external_id", name="uq_retailer_product_external"),
        Index("ix_retailer_products_canonical", "izdelek_id"),
        Index("ix_retailer_products_store_active", "trgovina_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trgovina_id: Mapped[int] = mapped_column(ForeignKey("trgovine.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ime: Mapped[str] = mapped_column(String(300), nullable=False)
    gtin: Mapped[str | None] = mapped_column(String(32))
    brand: Mapped[str | None] = mapped_column(String(200))
    kategorija: Mapped[str | None] = mapped_column(String(300))
    enota: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    izdelek_id: Mapped[int | None] = mapped_column(ForeignKey("izdelki.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    last_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_import_runs.id", ondelete="SET NULL")
    )

    trgovina: Mapped[Trgovina] = relationship(back_populates="retailer_products")
    izdelek: Mapped[Izdelek | None] = relationship()
    gtins: Mapped[list["RetailerProductGtin"]] = relationship(
        back_populates="retailer_product", cascade="all, delete-orphan"
    )
    price_snapshots: Mapped[list["RetailerPriceSnapshot"]] = relationship(
        back_populates="retailer_product", cascade="all, delete-orphan"
    )


class ProductGtin(Base):
    __tablename__ = "product_gtins"
    __table_args__ = (UniqueConstraint("gtin", name="uq_product_gtins_gtin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    izdelek_id: Mapped[int] = mapped_column(ForeignKey("izdelki.id", ondelete="CASCADE"), nullable=False)
    gtin: Mapped[str] = mapped_column(String(14), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    izdelek: Mapped[Izdelek] = relationship(back_populates="gtins")


class CatalogImportRun(Base):
    __tablename__ = "catalog_import_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'skipped')",
            name="ck_catalog_import_runs_status",
        ),
        Index("ix_catalog_import_runs_store_date", "trgovina_id", "captured_on", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trgovina_id: Mapped[int] = mapped_column(ForeignKey("trgovine.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    captured_on: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    products_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    products_mapped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    snapshots_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    prices_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)

    trgovina: Mapped[Trgovina] = relationship(back_populates="import_runs")


class RetailerProductGtin(Base):
    __tablename__ = "retailer_product_gtins"
    __table_args__ = (
        UniqueConstraint("retailer_product_id", "gtin", name="uq_retailer_product_gtin"),
        Index("ix_retailer_product_gtins_gtin", "gtin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_product_id: Mapped[int] = mapped_column(
        ForeignKey("retailer_products.id", ondelete="CASCADE"), nullable=False
    )
    gtin: Mapped[str] = mapped_column(String(14), nullable=False)

    retailer_product: Mapped[RetailerProduct] = relationship(back_populates="gtins")


class RetailerPriceSnapshot(Base):
    __tablename__ = "retailer_price_snapshots"
    __table_args__ = (
        CheckConstraint("effective_price >= 0", name="ck_retailer_snapshots_effective_nonnegative"),
        UniqueConstraint(
            "retailer_product_id", "captured_on", name="uq_retailer_snapshot_product_date"
        ),
        Index("ix_retailer_snapshots_date", "captured_on", "retailer_product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_product_id: Mapped[int] = mapped_column(
        ForeignKey("retailer_products.id", ondelete="CASCADE"), nullable=False
    )
    captured_on: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    effective_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    regular_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    promotion_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    lowest_30d_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    unit_base: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    promotion_type: Mapped[str | None] = mapped_column(String(100))
    promotion_starts_at: Mapped[datetime | None] = mapped_column(DateTime)
    promotion_ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    requires_loyalty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    promotion_data: Mapped[dict | list | None] = mapped_column(JSON)

    retailer_product: Mapped[RetailerProduct] = relationship(back_populates="price_snapshots")


# Compatibility for code that imported the original underscored class.
Seznam_izdelek = SeznamIzdelek
