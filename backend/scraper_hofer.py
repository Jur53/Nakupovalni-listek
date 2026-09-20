"""HOFER Slovenia anonymous walk-in catalog adapter."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .catalog_import import CatalogProduct, PriceObservation


BASE_URL = "https://www.hofer.si"
CATALOG_URL = "https://api.hofer.si/v3/product-search"
DEFAULT_STORE = "I032"
DEFAULT_TIMEOUT = (5, 30)
PAGE_SIZE = 60
MAX_CATALOG_PRODUCTS = 20_000
IMAGE_WIDTH = 600


class HoferError(RuntimeError):
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
    session.headers.update(
        {
            "Accept": "application/json",
        }
    )
    return session


def _cents(value, *, required: bool = False) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        if required:
            raise HoferError("HOFER product is missing its current price")
        return None
    try:
        cents = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HoferError(f"Invalid HOFER price in cents: {value!r}") from exc
    if not cents.is_finite() or cents != cents.to_integral_value() or cents <= 0:
        raise HoferError(f"Invalid HOFER price in cents: {value!r}")
    return (cents / 100).quantize(Decimal("0.01"))


def _localized_price(value) -> Decimal | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise HoferError(f"Invalid HOFER localized price: {value!r}")
    match = re.search(r"\d[\d.\s\xa0]*(?:,\d{1,2})?", value)
    if match is None:
        raise HoferError(f"Invalid HOFER localized price: {value!r}")
    cleaned = match.group(0).replace("\xa0", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") != 1 or len(cleaned.rsplit(".", 1)[1]) > 2:
        cleaned = cleaned.replace(".", "")
    try:
        price = Decimal(cleaned)
    except InvalidOperation as exc:
        raise HoferError(f"Invalid HOFER localized price: {value!r}") from exc
    if not price.is_finite() or price <= 0:
        raise HoferError(f"Invalid HOFER localized price: {value!r}")
    return price.quantize(Decimal("0.01"))


def _string(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _on_sale_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _unit_base(display_value) -> str | None:
    display = _string(display_value)
    if display is None or "/" not in display:
        return None
    return _string(display.split("/", 1)[1].replace("\xa0", " "))


def _category(raw: dict) -> str | None:
    categories = raw.get("categories") or []
    if not isinstance(categories, list):
        raise HoferError("HOFER product has an invalid categories shape")
    for category in categories:
        if isinstance(category, dict):
            name = _string(category.get("name"))
        else:
            name = _string(category)
        if name:
            return name
    return None


def _image_url(raw: dict, slug: str) -> str | None:
    assets = raw.get("assets") or []
    if not isinstance(assets, list):
        raise HoferError("HOFER product has an invalid assets shape")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        template = _string(asset.get("url"))
        if template is None:
            continue
        parsed = urlsplit(template)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            continue
        try:
            max_width = int(asset.get("maxWidth") or IMAGE_WIDTH)
        except (TypeError, ValueError):
            max_width = IMAGE_WIDTH
        width = min(IMAGE_WIDTH, max_width) if max_width > 0 else IMAGE_WIDTH
        return template.replace("{width}", str(width)).replace(
            "{slug}", quote(slug, safe="-._~")
        )
    return None


def parse_product(raw: dict, now: datetime | None = None) -> CatalogProduct:
    if not isinstance(raw, dict):
        raise HoferError("HOFER catalog contains a non-object product")
    sku = raw.get("sku")
    name = _string(raw.get("name"))
    if not isinstance(sku, str) or not sku.strip() or name is None:
        raise HoferError("HOFER product is missing its string SKU or name")

    price = raw.get("price")
    if not isinstance(price, dict):
        raise HoferError("HOFER product is missing its price object")
    effective_price = _cents(price.get("amountRelevant"), required=True)
    assert effective_price is not None
    previous_price = _localized_price(price.get("wasPriceDisplay"))
    discounted = previous_price is not None and previous_price > effective_price
    unit_price = _cents(
        price.get("comparison")
        if price.get("comparison") is not None
        else price.get("perUnit")
    )
    unit_display = (
        price.get("comparisonDisplay")
        if price.get("comparison") is not None
        else price.get("perUnitDisplay")
    )

    slug = _string(raw.get("urlSlugText"))
    product_url = f"{BASE_URL}/izdelek/{quote(slug, safe='-._~')}-{sku}" if slug else None
    on_sale_date = _string(raw.get("onSaleDate"))
    promotion_starts_at = _on_sale_datetime(on_sale_date)
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is not None:
        current_time = current_time.astimezone(UTC).replace(tzinfo=None)
    promotion_is_current = promotion_starts_at is None or promotion_starts_at <= current_time
    active_discount = discounted and promotion_is_current
    comparison_price = effective_price
    if discounted and not promotion_is_current:
        comparison_price = previous_price
    on_sale_display = _string(raw.get("onSaleDateDisplay"))
    badges = raw.get("badges")
    promotion_data = None
    if on_sale_date or on_sale_display or badges:
        promotion_data = {
            "onSaleDate": on_sale_date,
            "onSaleDateDisplay": on_sale_display,
            "badges": badges if isinstance(badges, list) else [],
        }

    return CatalogProduct(
        external_id=sku,
        name=name,
        # HOFER's public source exposes internal SKUs, not GTINs.
        gtins=(),
        brand=_string(raw.get("brandName")),
        category=_category(raw),
        unit=_string(raw.get("sellingSize")) or _string(raw.get("sellingUnitDisplay")),
        url=product_url,
        image_url=_image_url(raw, slug or name),
        price=PriceObservation(
            effective_price=comparison_price,
            regular_price=previous_price if discounted else effective_price,
            promotion_price=effective_price if active_discount else None,
            previous_price=previous_price,
            unit_price=unit_price,
            unit_base=_unit_base(unit_display),
            currency=str(price.get("currencyCode") or "EUR"),
            promotion_type="price-reduction" if active_discount else None,
            promotion_starts_at=promotion_starts_at,
            promotion_ends_at=None,
            requires_loyalty=False,
            promotion_data=promotion_data,
        ),
    )


def _pagination_integer(value, name: str) -> int:
    if isinstance(value, bool):
        raise HoferError(f"HOFER catalog {name} is invalid")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise HoferError(f"HOFER catalog {name} is invalid") from exc
    if str(number) != str(value).strip():
        raise HoferError(f"HOFER catalog {name} is invalid")
    return number


class HoferAdapter:
    retailer_name = "Hofer"
    catalog_is_complete = True

    def __init__(
        self,
        session: requests.Session | None = None,
        store_reference: str = DEFAULT_STORE,
        pause_seconds: float = 0.2,
    ):
        self.session = session or build_session()
        self.store_reference = store_reference
        self.pause_seconds = pause_seconds

    def _request_page(self, offset: int) -> dict:
        params = {
            "currency": "EUR",
            "serviceType": "walk-in",
            "servicePoint": self.store_reference,
            "limit": PAGE_SIZE,
            "offset": offset,
            "sort": "relevance",
        }
        try:
            response = self.session.get(CATALOG_URL, params=params, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "")[:1000]
            raise HoferError(f"HOFER catalog request failed: {exc}; {detail}") from exc
        except ValueError as exc:
            raise HoferError("HOFER catalog returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HoferError("HOFER catalog response has an invalid shape")
        return payload

    def fetch_catalog(self) -> list[CatalogProduct]:
        products_by_sku: dict[str, CatalogProduct] = {}
        expected_total = None
        offset = 0

        while expected_total is None or offset < expected_total:
            payload = self._request_page(offset)
            raw_products = payload.get("data")
            meta = payload.get("meta")
            pagination = meta.get("pagination") if isinstance(meta, dict) else None
            if not isinstance(raw_products, list) or not isinstance(pagination, dict):
                raise HoferError("HOFER catalog page has an invalid shape")
            if any(not isinstance(product, dict) for product in raw_products):
                raise HoferError("HOFER catalog page contains a non-object product")

            total = _pagination_integer(pagination.get("totalCount"), "total count")
            response_offset = _pagination_integer(pagination.get("offset"), "offset")
            response_limit = _pagination_integer(pagination.get("limit"), "limit")
            if not 0 <= total <= MAX_CATALOG_PRODUCTS:
                raise HoferError("HOFER catalog total is outside the allowed range")
            if response_offset != offset or response_limit != PAGE_SIZE:
                raise HoferError("HOFER catalog pagination is inconsistent")
            if expected_total is not None and total != expected_total:
                raise HoferError("HOFER catalog total changed during pagination")
            expected_total = total

            if not raw_products:
                if offset < total:
                    raise HoferError("HOFER pagination ended before the advertised total")
                break
            if offset + len(raw_products) > total:
                raise HoferError("HOFER catalog returned more products than advertised")

            for raw_product in raw_products:
                product = parse_product(raw_product)
                products_by_sku[product.external_id] = product

            offset += len(raw_products)
            if offset < total and self.pause_seconds:
                time.sleep(self.pause_seconds)

        return list(products_by_sku.values())
