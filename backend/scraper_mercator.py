"""Mercator catalog scraper and explicit canonical-price persistence workflow.

Run with: python -m backend.scraper_mercator CATEGORY_ID
"""

import argparse
import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from .database import SessionLocal
from .catalog_import import CatalogProduct, PriceObservation
from .models import Cena, RetailerProduct, Trgovina


BASE_URL = "https://mercatoronline.si"
CATALOG_URL = f"{BASE_URL}/products/browseProducts/getProducts"
CATEGORIES_URL = f"{BASE_URL}/products/categories/getCategories"
ALLOWED_HOSTS = {"mercatoronline.si", "www.mercatoronline.si"}
DEFAULT_TIMEOUT = (5, 20)
MAX_CATALOG_PRODUCTS = 20_000


class ScraperError(RuntimeError):
    pass


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "nakupovalni-listek/1.0 (+catalog import)"})
    return session


def _safe_mercator_url(path_or_url: str) -> str:
    url = urljoin(f"{BASE_URL}/", path_or_url)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ScraperError("Mercator response contained an untrusted product URL")
    return url


def _decimal_price(value) -> Decimal:
    cleaned = re.sub(r"[^0-9,.-]", "", str(value)).replace(",", ".")
    try:
        price = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ScraperError(f"Invalid price value: {value!r}")
    if not price.is_finite() or price < 0:
        raise ScraperError(f"Invalid price value: {value!r}")
    return price.quantize(Decimal("0.01"))


def dobi_ceno_mercator(url: str, session: requests.Session | None = None):
    url = _safe_mercator_url(url)
    client = session or build_session()
    try:
        response = client.get(url, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScraperError(f"Mercator product request failed: {exc}") from exc
    soup = BeautifulSoup(response.text, "html.parser")
    name_element = soup.find("h1", class_="lib-analytics-product-name")
    price_element = soup.find("span", class_="price")
    if name_element is None or price_element is None:
        raise ScraperError("Mercator product page is missing name or price")
    name = name_element.get_text(strip=True)
    if not name:
        raise ScraperError("Mercator product name is empty")
    return name, _decimal_price(price_element.get_text(strip=True))


def dobi_izdelke_kategorija(
    category_id: str,
    limit: int = 100,
    offset: int = 0,
    session: requests.Session | None = None,
):
    if not str(category_id).strip() or len(str(category_id)) > 100:
        raise ValueError("category_id must be between 1 and 100 characters")
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be nonnegative")
    params = {
        "limit": limit,
        "offset": offset,
        "filterData[categories]": category_id,
        "from": offset * limit,
    }
    client = session or build_session()
    try:
        response = client.get(CATALOG_URL, params=params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScraperError(f"Mercator catalog request failed: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise ScraperError("Mercator catalog response has an invalid products shape")
    if any(not isinstance(product, dict) for product in payload["products"]):
        raise ScraperError("Mercator catalog contains a non-object product")
    return payload


def pretvori_izdelek(raw_product: dict):
    data = raw_product.get("data")
    if not isinstance(data, dict):
        raise ScraperError("Mercator product is missing its data object")
    name = data.get("name")
    external_id = data.get("cinv")
    if not isinstance(name, str) or not name.strip() or external_id in (None, ""):
        raise ScraperError("Mercator product is missing name or cinv")
    gtins = data.get("gtins") or []
    if not isinstance(gtins, list) or (gtins and not isinstance(gtins[0], dict)):
        raise ScraperError("Mercator product has an invalid gtins shape")
    return {
        "ime": name.strip(),
        "cena": _decimal_price(data.get("current_price")),
        "cena_na_enoto": data.get("price_per_unit"),
        "enota_baza": data.get("price_per_unit_base"),
        "kategorija": data.get("category2"),
        "gtin": str(gtins[0].get("gtin")) if gtins and gtins[0].get("gtin") else None,
        "mercator_id": str(external_id),
        "url": _safe_mercator_url(str(raw_product.get("url") or "/")),
    }


def dobi_vse_izdelke_kategorija(
    category_id: str,
    limit: int = 100,
    session: requests.Session | None = None,
    pause_seconds: float = 0.2,
    raw: bool = False,
):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    client = session or build_session()
    all_products = []
    offset = 0
    fetched_count = 0
    expected_total = None
    while True:
        payload = dobi_izdelke_kategorija(category_id, limit, offset, client)
        raw_products = payload["products"]
        raw_total = payload.get("total")
        if raw_total is None and raw_products:
            raw_total = raw_products[0].get("total")
        try:
            total = int(raw_total) if raw_total is not None else None
        except (TypeError, ValueError):
            raise ScraperError("Mercator catalog total is invalid")
        if total is not None and (total < 0 or total > MAX_CATALOG_PRODUCTS):
            raise ScraperError("Mercator catalog total is outside the allowed range")
        if expected_total is not None and total is not None and total != expected_total:
            raise ScraperError("Mercator catalog total changed during pagination")
        expected_total = total if expected_total is None else expected_total
        if not raw_products:
            if expected_total is not None and fetched_count < expected_total:
                raise ScraperError("Mercator pagination ended before the advertised total")
            break
        all_products.extend(raw_products)
        fetched_count += len(raw_products)
        if len(all_products) > MAX_CATALOG_PRODUCTS:
            raise ScraperError("Mercator pagination exceeded the product safety limit")
        offset += 1
        if expected_total is not None and fetched_count >= expected_total:
            break
        if len(raw_products) < limit and expected_total is None:
            break
        if pause_seconds:
            time.sleep(pause_seconds)
    return all_products if raw else [pretvori_izdelek(product) for product in all_products]


def _mercator_datetime(value) -> datetime | None:
    if not value or str(value) == "1970-01-01":
        return None
    for format_string in ("%Y%m%d%H%M%S", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), format_string)
        except ValueError:
            pass
    return None


def _optional_price(value) -> Decimal | None:
    if value in (None, ""):
        return None
    price = _decimal_price(value)
    return price if price > 0 else None


def _mercator_catalog_product(
    raw_product: dict,
    now: datetime | None = None,
) -> CatalogProduct:
    legacy = pretvori_izdelek(raw_product)
    data = raw_product["data"]
    discounts = data.get("discounts") or []
    if not isinstance(discounts, list):
        raise ScraperError("Mercator product has an invalid discounts shape")
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is not None:
        current_time = current_time.astimezone(UTC).replace(tzinfo=None)

    def is_current(discount: dict) -> bool:
        start_value = discount.get("valid_from")
        end_value = discount.get("valid_to")
        start = _mercator_datetime(start_value)
        end = _mercator_datetime(end_value)
        if start_value and start is None:
            return False
        if end_value and end is None:
            return False
        return (start is None or start <= current_time) and (end is None or current_time <= end)

    active_discounts = [discount for discount in discounts if is_current(discount)]
    loyalty_discounts = [
        discount
        for discount in active_discounts
        if discount.get("clubs") or discount.get("clubs_array")
    ]
    public_discounts = [
        discount for discount in active_discounts if discount not in loyalty_discounts
    ]
    current_price = legacy["cena"]
    regular_price = _optional_price(data.get("normal_price")) or current_price
    public_candidates = [
        (price, discount)
        for discount in public_discounts
        if (price := _optional_price(discount.get("discount_price"))) is not None
    ]
    if public_discounts:
        if public_candidates:
            effective_price, active_discount = min(public_candidates, key=lambda item: item[0])
        else:
            effective_price = current_price
            active_discount = public_discounts[0]
    elif loyalty_discounts:
        effective_price = regular_price
        active_discount = loyalty_discounts[0]
    elif discounts:
        effective_price = regular_price
        active_discount = None
    else:
        effective_price = current_price
        active_discount = None
    promotion_price = effective_price if public_discounts and effective_price < regular_price else None
    gtins = tuple(
        str(item["gtin"])
        for item in data.get("gtins") or []
        if isinstance(item, dict) and item.get("gtin")
    )
    unit = data.get("invoice_unit")
    unit_quantity = data.get("unit_quantity")
    if unit_quantity and unit:
        unit = f"{unit_quantity} {unit}"
    return CatalogProduct(
        external_id=legacy["mercator_id"],
        name=legacy["ime"],
        gtins=gtins,
        brand=data.get("brand_name"),
        category=data.get("category1") or data.get("category2"),
        unit=str(unit) if unit else None,
        url=legacy["url"],
        image_url=_safe_mercator_url(str(raw_product["mainImageSrc"]))
        if raw_product.get("mainImageSrc")
        else None,
        price=PriceObservation(
            effective_price=effective_price,
            regular_price=regular_price,
            promotion_price=promotion_price,
            lowest_30d_price=_optional_price(data.get("pc30_price")),
            unit_price=_optional_price(data.get("price_per_unit")),
            unit_base=str(data["price_per_unit_base"])
            if data.get("price_per_unit_base")
            else None,
            promotion_type=str(active_discount.get("group_type") or active_discount.get("hover_text"))
            if active_discount
            else None,
            promotion_starts_at=_mercator_datetime(active_discount.get("valid_from"))
            if active_discount
            else None,
            promotion_ends_at=_mercator_datetime(active_discount.get("valid_to"))
            if active_discount
            else _mercator_datetime(data.get("offer_expires_on")),
            requires_loyalty=bool(loyalty_discounts and not public_discounts),
            promotion_data=discounts or None,
        ),
    )


class MercatorAdapter:
    retailer_name = "Mercator"
    catalog_is_complete = True

    def __init__(self, session: requests.Session | None = None, pause_seconds: float = 0.1):
        self.session = session or build_session()
        self.pause_seconds = pause_seconds

    def _food_categories(self) -> list[str]:
        try:
            response = self.session.get(CATEGORIES_URL, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ScraperError(f"Mercator category request failed: {exc}") from exc
        if not isinstance(payload, list):
            raise ScraperError("Mercator category response has an invalid shape")
        categories = []
        for item in payload:
            category = item.get("Category") if isinstance(item, dict) else None
            if (
                isinstance(category, dict)
                and str(category.get("has_food_stuff")) == "1"
                and category.get("id")
                and int(category.get("no_of_products") or 0) > 0
            ):
                categories.append(str(category["id"]))
        if not categories:
            raise ScraperError("Mercator returned no populated food categories")
        return categories

    def fetch_catalog(self) -> list[CatalogProduct]:
        products_by_id: dict[str, CatalogProduct] = {}
        for category_id in self._food_categories():
            for product in dobi_vse_izdelke_kategorija(
                category_id,
                limit=100,
                session=self.session,
                pause_seconds=self.pause_seconds,
                raw=True,
            ):
                if not isinstance(product.get("data"), dict):
                    continue
                converted = _mercator_catalog_product(product)
                products_by_id[converted.external_id] = converted
        return list(products_by_id.values())


def persist_catalog(db: Session, products: list[dict], captured_on: date | None = None) -> tuple[int, int]:
    """Upsert retailer rows; persist prices only for already mapped canonical products."""
    captured_on = captured_on or date.today()
    store = db.scalar(select(Trgovina).where(Trgovina.ime == "Mercator"))
    if store is None:
        store = Trgovina(ime="Mercator")
        db.add(store)
        db.flush()
    catalog_count = 0
    price_count = 0
    for product in products:
        external_id = str(product["mercator_id"])
        retailer_product = db.scalar(
            select(RetailerProduct).where(
                RetailerProduct.trgovina_id == store.id,
                RetailerProduct.external_id == external_id,
            )
        )
        if retailer_product is None:
            retailer_product = RetailerProduct(
                trgovina_id=store.id,
                external_id=external_id,
                ime=product["ime"],
            )
            db.add(retailer_product)
            db.flush()
        retailer_product.ime = product["ime"]
        retailer_product.gtin = product.get("gtin")
        retailer_product.url = product.get("url")
        catalog_count += 1
        if retailer_product.izdelek_id is None:
            continue
        price = db.scalar(
            select(Cena).where(
                Cena.izdelek_id == retailer_product.izdelek_id,
                Cena.trgovina_id == store.id,
                Cena.datum_zajema == captured_on,
            )
        )
        if price is None:
            price = Cena(
                izdelek_id=retailer_product.izdelek_id,
                trgovina_id=store.id,
                datum_zajema=captured_on,
                cena=product["cena"],
            )
            db.add(price)
        else:
            price.cena = product["cena"]
        price_count += 1
    db.flush()
    return catalog_count, price_count


def main():
    parser = argparse.ArgumentParser(description="Import a Mercator category into retailer_products")
    parser.add_argument("category_id")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    products = dobi_vse_izdelke_kategorija(args.category_id, limit=args.limit)
    with SessionLocal.begin() as db:
        catalog_count, price_count = persist_catalog(db, products)
    print(f"Upserted {catalog_count} retailer products and {price_count} mapped prices")


if __name__ == "__main__":
    main()
