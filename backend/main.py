from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from . import models, schemas
from .auth import (
    check_auth_rate_limit,
    create_access_token,
    get_current_user,
    normalize_email,
    password_hash,
    verify_login_password,
)
from .config import get_settings
from .database import get_db


settings = get_settings()
ALEMBIC_HEAD = "0005_catalog_taxonomy"
MAX_LIST_ITEMS = 100
app = FastAPI(title="Nakupovalni listek API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health", tags=["operations"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["operations"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        schema = inspect(db.get_bind())
        required = {
            "users": {"id", "email", "password_hash", "is_active", "is_legacy"},
            "trgovine": {"id", "ime"},
            "categories": {"id", "slug", "name", "parent_id", "sort_order", "is_visible"},
            "izdelki": {"id", "ime", "category_id"},
            "cene": {"id", "izdelek_id", "trgovina_id", "cena", "datum_zajema"},
            "seznami": {"id", "user_id", "ime"},
            "seznam_izdelki": {"seznam_id", "izdelek_id", "kolicina"},
            "retailer_products": {
                "id",
                "trgovina_id",
                "external_id",
                "izdelek_id",
                "is_active",
                "last_seen_at",
            },
            "product_gtins": {"izdelek_id", "gtin"},
            "catalog_import_runs": {"status", "products_seen"},
            "retailer_product_gtins": {"retailer_product_id", "gtin"},
            "retailer_price_snapshots": {
                "retailer_product_id",
                "captured_on",
                "effective_price",
            },
        }
        for table, columns in required.items():
            if not schema.has_table(table):
                raise RuntimeError(f"Missing required table: {table}")
            actual = {column["name"] for column in schema.get_columns(table)}
            if not columns <= actual:
                raise RuntimeError(f"Required columns are missing from {table}")
        if schema.has_table("alembic_version"):
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != ALEMBIC_HEAD:
                raise RuntimeError("Database migration is not at the required revision")
        elif settings.app_env == "production":
            raise RuntimeError("Alembic version table is missing")
    except (SQLAlchemyError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Database schema is not ready") from exc
    return {"status": "ready"}


def latest_prices_subquery():
    ranked = select(
        models.Cena.id,
        models.Cena.izdelek_id,
        models.Cena.trgovina_id,
        models.Cena.cena,
        models.Cena.datum_zajema,
        func.row_number().over(
            partition_by=(models.Cena.izdelek_id, models.Cena.trgovina_id),
            order_by=(models.Cena.datum_zajema.desc(), models.Cena.id.desc()),
        ).label("row_number"),
    ).subquery()
    return select(ranked).where(ranked.c.row_number == 1).subquery()


def available_latest_prices_subquery(store_ids: list[int] | None = None):
    latest = latest_prices_subquery()
    active_offer = (
        select(models.RetailerProduct.id)
        .where(
            models.RetailerProduct.izdelek_id == latest.c.izdelek_id,
            models.RetailerProduct.trgovina_id == latest.c.trgovina_id,
            models.RetailerProduct.is_active.is_(True),
        )
        .exists()
    )
    query = (
        select(
            latest.c.izdelek_id,
            latest.c.trgovina_id,
            models.Trgovina.ime.label("trgovina_ime"),
            latest.c.cena,
            latest.c.datum_zajema,
        )
        .join(models.Trgovina, models.Trgovina.id == latest.c.trgovina_id)
        .where(active_offer)
    )
    if store_ids is not None:
        query = query.where(latest.c.trgovina_id.in_(store_ids))
    return query.subquery()


def validate_store_ids(db: Session, store_ids: list[int] | None) -> list[int] | None:
    if store_ids is None:
        return None
    if any(store_id <= 0 for store_id in store_ids) or len(store_ids) != len(set(store_ids)):
        raise HTTPException(status_code=422, detail="Store IDs must be positive and unique")
    known = set(db.scalars(select(models.Trgovina.id).where(models.Trgovina.id.in_(store_ids))))
    unknown = sorted(set(store_ids) - known)
    if unknown:
        raise HTTPException(status_code=404, detail={"message": "Unknown store IDs", "ids": unknown})
    return store_ids


def category_rows(db: Session) -> list[models.Category]:
    return list(
        db.scalars(
            select(models.Category).order_by(
                models.Category.parent_id.nulls_first(),
                models.Category.sort_order,
                models.Category.id,
            )
        )
    )


def descendant_category_ids(categories: list[models.Category], category_id: int) -> set[int]:
    children: dict[int | None, list[int]] = {}
    for category in categories:
        children.setdefault(category.parent_id, []).append(category.id)
    result: set[int] = set()
    pending = [category_id]
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(children.get(current, []))
    return result


def category_path(category_id: int | None, categories_by_id: dict[int, models.Category]) -> list[str]:
    path = []
    seen = set()
    while category_id is not None and category_id not in seen:
        seen.add(category_id)
        category = categories_by_id.get(category_id)
        if category is None:
            break
        path.append(category.name)
        category_id = category.parent_id
    return list(reversed(path))


def build_category_tree(
    db: Session,
    store_ids: list[int] | None,
    categories: list[models.Category] | None = None,
) -> list[schemas.CategoryOut]:
    categories = categories if categories is not None else category_rows(db)
    if not categories:
        return []
    available = available_latest_prices_subquery(store_ids)
    direct_counts = dict(
        db.execute(
            select(models.Izdelek.category_id, func.count(func.distinct(models.Izdelek.id)))
            .where(
                models.Izdelek.category_id.is_not(None),
                models.Izdelek.id.in_(select(available.c.izdelek_id)),
            )
            .group_by(models.Izdelek.category_id)
        ).all()
    )
    by_parent: dict[int | None, list[models.Category]] = {}
    for category in categories:
        if category.is_visible:
            by_parent.setdefault(category.parent_id, []).append(category)
    for siblings in by_parent.values():
        siblings.sort(key=lambda category: (category.sort_order, category.id))

    def node(category: models.Category) -> schemas.CategoryOut | None:
        children = [
            child_node
            for child in by_parent.get(category.id, [])
            if (child_node := node(child)) is not None
        ]
        product_count = direct_counts.get(category.id, 0) + sum(
            child.product_count for child in children
        )
        if product_count == 0:
            return None
        return schemas.CategoryOut(
            id=category.id,
            slug=category.slug,
            name=category.name,
            product_count=product_count,
            children=children,
        )

    return [
        root
        for category in by_parent.get(None, [])
        if (root := node(category)) is not None
    ]


@app.get("/categories", response_model=list[schemas.CategoryOut])
def get_categories(
    trgovina_ids: list[int] | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
):
    store_ids = validate_store_ids(db, trgovina_ids)
    return build_category_tree(db, store_ids)


@app.post("/auth/register", response_model=schemas.TokenOut, status_code=201)
def register(payload: schemas.RegisterIn, request: Request, db: Session = Depends(get_db)):
    check_auth_rate_limit(request, "register")
    user = models.User(
        email=normalize_email(str(payload.email)),
        password_hash=password_hash.hash(payload.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered")
    db.refresh(user)
    return schemas.TokenOut(access_token=create_access_token(user.id))


@app.post("/auth/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginIn, request: Request, db: Session = Depends(get_db)):
    check_auth_rate_limit(request, "login")
    user = db.scalar(select(models.User).where(models.User.email == normalize_email(str(payload.email))))
    if not verify_login_password(user, payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return schemas.TokenOut(access_token=create_access_token(user.id))


@app.get("/auth/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(get_current_user)):
    return user


@app.get("/trgovine", response_model=list[schemas.TrgovinaOut])
def get_trgovine(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return db.scalars(select(models.Trgovina).order_by(models.Trgovina.id).offset(offset).limit(limit)).all()


@app.get("/izdelki", response_model=schemas.IzdelkiPageOut)
def get_izdelki(
    q: str | None = Query(default=None, max_length=100),
    kategorija: str | None = Query(default=None, max_length=100),
    kategorija_id: int | None = Query(default=None, gt=0),
    trgovina_ids: list[int] | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    store_ids = validate_store_ids(db, trgovina_ids)
    available = available_latest_prices_subquery(store_ids)
    ranked_offers = select(
        available,
        func.row_number().over(
            partition_by=available.c.izdelek_id,
            order_by=(available.c.cena, available.c.trgovina_id),
        ).label("offer_rank"),
    ).subquery()
    cheapest_offers = select(ranked_offers).where(ranked_offers.c.offer_rank == 1).subquery()
    available_product_ids = select(cheapest_offers.c.izdelek_id)
    taxonomy_categories = category_rows(db)
    categories_by_id = {category.id: category for category in taxonomy_categories}
    filters = []
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                models.Izdelek.ime.ilike(pattern, escape="\\"),
                models.Izdelek.kategorija.ilike(pattern, escape="\\"),
            )
        )
    if kategorija and kategorija.strip():
        filters.append(models.Izdelek.kategorija == kategorija.strip())
    if taxonomy_categories:
        visible_ids = [category.id for category in taxonomy_categories if category.is_visible]
        filters.append(models.Izdelek.category_id.in_(visible_ids))
    if kategorija_id is not None:
        if kategorija_id not in categories_by_id:
            raise HTTPException(status_code=404, detail="Category does not exist")
        filters.append(
            models.Izdelek.category_id.in_(
                descendant_category_ids(taxonomy_categories, kategorija_id)
            )
        )

    query = select(models.Izdelek).where(models.Izdelek.id.in_(available_product_ids), *filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    products = db.scalars(
        query.order_by(models.Izdelek.kategorija.nulls_last(), models.Izdelek.ime, models.Izdelek.id)
        .offset(offset)
        .limit(limit)
    ).all()
    product_ids = [product.id for product in products]
    offers_by_product: dict[int, list[dict]] = {product_id: [] for product_id in product_ids}
    for row in db.execute(
        select(available)
        .where(available.c.izdelek_id.in_(product_ids))
        .order_by(available.c.izdelek_id, available.c.cena, available.c.trgovina_id)
    ).mappings():
        offers_by_product[row["izdelek_id"]].append(dict(row))
    legacy_categories_query = select(models.Izdelek.kategorija).where(
        models.Izdelek.kategorija.is_not(None),
        models.Izdelek.id.in_(available_product_ids),
    )
    if taxonomy_categories:
        legacy_categories_query = legacy_categories_query.where(
            models.Izdelek.category_id.in_(visible_ids)
        )
    categories = db.scalars(
        legacy_categories_query.distinct().order_by(models.Izdelek.kategorija)
    ).all()
    return schemas.IzdelkiPageOut(
        items=[
            schemas.IzdelekOut(
                id=product.id,
                ime=product.ime,
                kategorija=product.kategorija,
                kategorija_id=product.category_id,
                kategorija_pot=category_path(product.category_id, categories_by_id),
                enota=product.enota,
                najcenejsa_ponudba=schemas.NajcenejsaPonudba(
                    trgovina_id=offers_by_product[product.id][0]["trgovina_id"],
                    ime_trgovina=offers_by_product[product.id][0]["trgovina_ime"],
                    cena=offers_by_product[product.id][0]["cena"],
                    datum_zajema=offers_by_product[product.id][0]["datum_zajema"],
                ),
                ponudbe=[
                    schemas.NajcenejsaPonudba(
                        trgovina_id=offer["trgovina_id"],
                        ime_trgovina=offer["trgovina_ime"],
                        cena=offer["cena"],
                        datum_zajema=offer["datum_zajema"],
                    )
                    for offer in offers_by_product[product.id]
                ],
            )
            for product in products
        ],
        total=total,
        offset=offset,
        limit=limit,
        categories=list(categories),
        category_tree=build_category_tree(db, store_ids, taxonomy_categories),
    )


@app.get("/cene", response_model=list[schemas.CenaDetajlOut])
def get_cene(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    latest = available_latest_prices_subquery()
    rows = db.execute(
        select(
            latest.c.izdelek_id,
            models.Izdelek.ime.label("ime_izdelek"),
            latest.c.trgovina_id,
            latest.c.trgovina_ime.label("ime_trgovina"),
            latest.c.cena,
            latest.c.datum_zajema,
        )
        .join(models.Izdelek, models.Izdelek.id == latest.c.izdelek_id)
        .order_by(latest.c.izdelek_id, latest.c.trgovina_id)
        .offset(offset)
        .limit(limit)
    ).mappings()
    return list(rows)


@app.post("/primerjava", response_model=schemas.PrimerjavaOut)
def primerjaj_cene(zahteva: schemas.PrimerjavaIn, db: Session = Depends(get_db)):
    quantities = {item.izdelek_id: item.kolicina for item in zahteva.items}
    product_ids = list(quantities)
    products = {
        product.id: product
        for product in db.scalars(select(models.Izdelek).where(models.Izdelek.id.in_(product_ids)))
    }
    unknown = sorted(set(product_ids) - products.keys())
    if unknown:
        raise HTTPException(status_code=404, detail={"message": "Unknown product IDs", "ids": unknown})

    store_ids = validate_store_ids(db, list(zahteva.trgovina_ids) if zahteva.trgovina_ids else None)
    latest = available_latest_prices_subquery(store_ids)
    rows = db.execute(
        select(
            latest.c.izdelek_id,
            latest.c.trgovina_id,
            latest.c.cena,
            latest.c.trgovina_ime,
        )
        .where(latest.c.izdelek_id.in_(product_ids))
        .order_by(latest.c.trgovina_id, latest.c.izdelek_id)
    ).mappings().all()

    by_store: dict[int, dict[int, dict]] = {}
    store_names: dict[int, str] = {}
    by_product: dict[int, list[dict]] = {product_id: [] for product_id in product_ids}
    for row in rows:
        record = dict(row)
        by_store.setdefault(row["trgovina_id"], {})[row["izdelek_id"]] = record
        store_names[row["trgovina_id"]] = row["trgovina_ime"]
        by_product[row["izdelek_id"]].append(record)

    complete = []
    required = set(product_ids)
    for store_id, prices in by_store.items():
        if prices.keys() >= required:
            total = sum(
                (prices[product_id]["cena"] * quantities[product_id] for product_id in product_ids),
                Decimal("0.00"),
            )
            complete.append((total, store_id, store_names[store_id]))
    complete.sort(key=lambda value: (value[0], value[1]))

    split = []
    for product_id in product_ids:
        choices = sorted(by_product[product_id], key=lambda row: (row["cena"], row["trgovina_id"]))
        if not choices:
            raise HTTPException(status_code=422, detail=f"No current price is available for product {product_id}")
        choice = choices[0]
        split.append(
            schemas.IzdelekNajcenejsi(
                izdelek_id=product_id,
                ime_izdelek=products[product_id].ime,
                trgovina_id=choice["trgovina_id"],
                ime_trgovina=choice["trgovina_ime"],
                kolicina=quantities[product_id],
                cena_na_enoto=choice["cena"],
                skupna_cena=choice["cena"] * quantities[product_id],
            )
        )
    split.sort(key=lambda item: item.izdelek_id)
    split_total = sum((item.skupna_cena for item in split), Decimal("0.00"))
    cheapest = complete[0] if complete else None
    most_expensive = max(complete, key=lambda value: (value[0], -value[1])) if complete else None
    return schemas.PrimerjavaOut(
        celoten_nakup_na_voljo=cheapest is not None,
        cene_po_trgovinah=[
            schemas.SkupnaCenaTrgovina(trgovina_id=store_id, ime_trgovina=name, skupna_cena=total)
            for total, store_id, name in complete
        ],
        najcenejsa_trgovina_id=cheapest[1] if cheapest else None,
        najcenejsa_trgovina=cheapest[2] if cheapest else None,
        prihranek=most_expensive[0] - cheapest[0] if cheapest and most_expensive else None,
        razdeljen_seznam=split,
        skupna_cena_razdeljeno=split_total,
        dodatni_prihranek=cheapest[0] - split_total if cheapest else None,
    )


def owned_list(
    db: Session,
    list_id: int,
    user_id: int,
    *,
    for_update: bool = False,
) -> models.Seznam:
    query = (
        select(models.Seznam)
        .options(
            selectinload(models.Seznam.izdelki).selectinload(models.SeznamIzdelek.izdelek)
        )
        .where(models.Seznam.id == list_id, models.Seznam.user_id == user_id)
    )
    if for_update:
        query = query.with_for_update()
    shopping_list = db.scalar(query)
    if shopping_list is None:
        raise HTTPException(status_code=404, detail="Seznam ne obstaja")
    return shopping_list


@app.post("/seznami", response_model=schemas.SeznamDetajlOut, status_code=201)
def ustvari_seznam(
    zahteva: schemas.SeznamIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    product_ids = [item.izdelek_id for item in zahteva.items]
    products = {
        product.id: product
        for product in db.scalars(select(models.Izdelek).where(models.Izdelek.id.in_(product_ids)))
    }
    unknown = sorted(set(product_ids) - products.keys())
    if unknown:
        raise HTTPException(status_code=404, detail={"message": "Unknown product IDs", "ids": unknown})
    shopping_list = models.Seznam(user_id=user.id, ime=zahteva.ime)
    shopping_list.izdelki = [
        models.SeznamIzdelek(izdelek=products[item.izdelek_id], kolicina=item.kolicina)
        for item in zahteva.items
    ]
    db.add(shopping_list)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="List conflicts with existing data")
    return list_detail(owned_list(db, shopping_list.id, user.id))


@app.post("/seznami/{seznam_id}/izdelki", response_model=schemas.SeznamIzdelekOut, status_code=201)
def dodaj_izdelek_na_seznam(
    seznam_id: int,
    zahteva: schemas.SeznamIzdelekIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    owned_list(db, seznam_id, user.id, for_update=True)
    item_count = db.scalar(
        select(func.count())
        .select_from(models.SeznamIzdelek)
        .where(models.SeznamIzdelek.seznam_id == seznam_id)
    )
    if item_count >= MAX_LIST_ITEMS:
        raise HTTPException(status_code=409, detail="Shopping list item limit reached")
    if db.get(models.Izdelek, zahteva.izdelek_id) is None:
        raise HTTPException(status_code=404, detail="Izdelek ne obstaja")
    item = models.SeznamIzdelek(
        seznam_id=seznam_id, izdelek_id=zahteva.izdelek_id, kolicina=zahteva.kolicina
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Izdelek je ze na seznamu")
    db.refresh(item)
    return item


def list_detail(shopping_list: models.Seznam) -> schemas.SeznamDetajlOut:
    return schemas.SeznamDetajlOut(
        id=shopping_list.id,
        ime=shopping_list.ime,
        ustvarjen=shopping_list.ustvarjen,
        izdelki=[
            schemas.SeznamIzdelekDetajl(
                izdelek_id=item.izdelek_id,
                ime_izdelek=item.izdelek.ime,
                kategorija=item.izdelek.kategorija,
                enota=item.izdelek.enota,
                kolicina=item.kolicina,
            )
            for item in shopping_list.izdelki
        ],
    )


@app.get("/seznami/{seznam_id}", response_model=schemas.SeznamDetajlOut)
def get_seznam(
    seznam_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return list_detail(owned_list(db, seznam_id, user.id))


@app.get("/seznami", response_model=list[schemas.SeznamOut])
def get_seznami(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return db.scalars(
        select(models.Seznam)
        .where(models.Seznam.user_id == user.id)
        .order_by(models.Seznam.ustvarjen.desc(), models.Seznam.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
