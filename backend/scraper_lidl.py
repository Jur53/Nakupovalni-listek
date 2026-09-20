"""Lidl Slovenia anonymous grocery catalog adapter."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .catalog_import import CatalogProduct, PriceObservation, normalize_gtin


BASE_URL = "https://www.lidl.si"
CATALOG_URL = f"{BASE_URL}/q/api/category/c/hrana-in-pijaca/s10068374"
DEFAULT_TIMEOUT = (5, 30)
DEFAULT_PAGE_SIZE = 108
MAX_CATALOG_PRODUCTS = 20_000
ACCEPT_HEADER = "application/mindshift.search+json;version=2"
CATALOG_PARAMS = {
    "assortment": "SI",
    "locale": "sl_SI",
    "version": "v2.0.0",
    "pageId": "10068374",
}
LIDL_HOSTS = {"lidl.si", "www.lidl.si"}


class LidlError(RuntimeError):
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
            "User-Agent": "nakupovalni-listek/1.0 (+catalog import)",
            "Accept": ACCEPT_HEADER,
        }
    )
    return session


def _decimal(value) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    cleaned = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.-]", "", cleaned)
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result.quantize(Decimal("0.01"))


def _datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_active(price: dict, now: datetime) -> bool:
    start_value = price.get("startDate")
    start = _datetime(start_value)
    if start_value and start is None:
        return False
    if start is not None and now < start:
        return False

    exclusive_value = price.get("endDateExclusive")
    exclusive_end = _datetime(exclusive_value)
    if exclusive_value and exclusive_end is None:
        return False
    if exclusive_end is not None:
        return now < exclusive_end

    end_value = price.get("endDate")
    end = _datetime(end_value)
    if end_value and end is None:
        return False
    return end is None or now <= end


def _safe_product_url(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(f"{BASE_URL}/", value.strip())
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in LIDL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return url


def _safe_image_url(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("image") or value.get("url") or value.get("src")
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(f"{BASE_URL}/", value.strip())
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return url


def _image_url(data: dict) -> str | None:
    candidates = [data.get("image"), data.get("image_V1")]
    for key in ("imageList", "imageList_V1", "images"):
        values = data.get(key) or []
        if isinstance(values, list):
            candidates.extend(values)
    for candidate in candidates:
        url = _safe_image_url(candidate)
        if url:
            return url
    return None


def _default_region_price(data: dict) -> tuple[str, dict] | None:
    regions = data.get("regionsV2")
    if isinstance(regions, dict):
        region_values = regions.values()
    elif isinstance(regions, list):
        region_values = regions
    else:
        return None

    default_region = next(
        (region for region in region_values if isinstance(region, dict) and region.get("isDefault") is True),
        None,
    )
    if default_region is None or default_region.get("regionPriceId") in (None, ""):
        return None
    region_price_id = str(default_region["regionPriceId"])
    prices = data.get("regionsPrices")
    if not isinstance(prices, dict):
        return None
    region_price = prices.get(region_price_id)
    if region_price is None:
        region_price = prices.get(default_region["regionPriceId"])
    if not isinstance(region_price, dict):
        return None
    return region_price_id, region_price


def _unit_price(price: dict) -> tuple[Decimal | None, str | None]:
    base_price = price.get("basePrice")
    text = base_price.get("text") if isinstance(base_price, dict) else None
    if not isinstance(text, str) or "=" not in text:
        return None, None
    unit_base, raw_price = (part.strip() for part in text.split("=", 1))
    unit_price = _decimal(raw_price)
    return (unit_price, unit_base) if unit_price and unit_base else (None, None)


def _string(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_product(raw_item: dict, now: datetime | None = None) -> CatalogProduct | None:
    """Normalize one search item, or skip it when no active public price exists."""
    if not isinstance(raw_item, dict):
        raise LidlError("Lidl catalog contains a non-object item")
    gridbox = raw_item.get("gridbox")
    data = gridbox.get("data") if isinstance(gridbox, dict) else None
    if not isinstance(data, dict):
        raise LidlError("Lidl product is missing its gridbox data")

    external_id = raw_item.get("code") or gridbox.get("productId") or data.get("erpNumber")
    keyfacts = data.get("keyfacts") if isinstance(data.get("keyfacts"), dict) else {}
    meta = gridbox.get("meta") if isinstance(gridbox.get("meta"), dict) else {}
    name = (
        _string(data.get("fullTitle"))
        or _string(keyfacts.get("fullTitle"))
        or _string(meta.get("fullTitle"))
        or _string(data.get("title"))
        or _string(keyfacts.get("title"))
    )
    if external_id in (None, "") or name is None:
        raise LidlError("Lidl product is missing its stable ID or name")

    selected = _default_region_price(data)
    if selected is None:
        return None
    region_price_id, region_price = selected
    current_price = region_price.get("currentPrice")
    if not isinstance(current_price, dict) or not _is_active(current_price, _utc(now)):
        return None
    effective_price = _decimal(current_price.get("price"))
    if effective_price is None:
        return None

    discount = current_price.get("discount")
    discount = discount if isinstance(discount, dict) else {}
    comparators = (
        _decimal(current_price.get("oldPrice")),
        _decimal(discount.get("deletedPrice")),
    )
    regular_price = next(
        (candidate for candidate in comparators if candidate is not None and candidate > effective_price),
        effective_price,
    )
    has_discount = bool(
        discount.get("showDiscount") is True
        or (_decimal(discount.get("absoluteDiscount")) is not None)
        or (_decimal(discount.get("percentageDiscount")) is not None)
    )
    unit_price, unit_base = _unit_price(current_price)
    brand = data.get("brand")
    brand_name = brand.get("name") if isinstance(brand, dict) else brand
    gtin = normalize_gtin(meta.get("ean"))
    packaging = current_price.get("packaging")
    unit = packaging.get("text") if isinstance(packaging, dict) else None
    start = _datetime(current_price.get("startDate"))
    end = _datetime(current_price.get("endDate")) or _datetime(current_price.get("endDateExclusive"))

    return CatalogProduct(
        external_id=str(external_id),
        name=name,
        gtins=(gtin,) if gtin else (),
        brand=_string(brand_name),
        category=_string(keyfacts.get("wonCategoryPrimary")),
        unit=_string(unit),
        url=_safe_product_url(data.get("canonicalUrl") or data.get("canonicalPath")),
        image_url=_image_url(data),
        price=PriceObservation(
            effective_price=effective_price,
            regular_price=regular_price,
            promotion_price=effective_price if has_discount else None,
            unit_price=unit_price,
            unit_base=unit_base,
            currency=str(current_price.get("currencyCode") or "EUR"),
            promotion_type=str(discount.get("type") or "discount") if has_discount else None,
            promotion_starts_at=start.replace(tzinfo=None) if has_discount and start else None,
            promotion_ends_at=end.replace(tzinfo=None) if has_discount and end else None,
            requires_loyalty=False,
            promotion_data={"regionPriceId": region_price_id, **region_price},
        ),
    )


class LidlAdapter:
    retailer_name = "Lidl"
    catalog_is_complete = True

    def __init__(
        self,
        session: requests.Session | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        pause_seconds: float = 0.1,
        now: datetime | None = None,
    ):
        if not 1 <= page_size <= DEFAULT_PAGE_SIZE:
            raise ValueError(f"page_size must be 1..{DEFAULT_PAGE_SIZE}")
        self.session = session or build_session()
        self.page_size = page_size
        self.pause_seconds = pause_seconds
        self.now = now

    def _request_page(self, offset: int) -> dict:
        params = {**CATALOG_PARAMS, "offset": offset, "fetchsize": self.page_size}
        try:
            response = self.session.get(CATALOG_URL, params=params, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise LidlError(f"Lidl catalog request failed: {exc}") from exc
        except ValueError as exc:
            raise LidlError("Lidl catalog returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise LidlError("Lidl catalog response has an invalid shape")
        return payload

    def fetch_catalog(self) -> list[CatalogProduct]:
        products_by_id: dict[str, CatalogProduct] = {}
        offset = 0
        expected_total: int | None = None

        while True:
            payload = self._request_page(offset)
            items = payload.get("items")
            try:
                total = int(payload["numFound"])
                response_offset = int(payload["offset"])
                response_size = int(payload["fetchsize"])
            except (KeyError, TypeError, ValueError) as exc:
                raise LidlError("Lidl catalog pagination is invalid") from exc
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise LidlError("Lidl catalog items have an invalid shape")
            if not 0 <= total <= MAX_CATALOG_PRODUCTS or response_offset != offset:
                raise LidlError("Lidl catalog pagination is inconsistent")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise LidlError("Lidl catalog total changed during pagination")
            if not 1 <= response_size <= DEFAULT_PAGE_SIZE:
                raise LidlError("Lidl catalog fetch size is invalid")
            if not items:
                if offset < total:
                    raise LidlError("Lidl pagination ended before the advertised total")
                break

            for item in items:
                product = parse_product(item, now=self.now)
                if product is not None:
                    products_by_id[product.external_id] = product

            next_offset = offset + len(items)
            if next_offset > MAX_CATALOG_PRODUCTS:
                raise LidlError("Lidl pagination exceeded the product safety limit")
            if next_offset >= total:
                break
            offset = next_offset
            if self.pause_seconds:
                time.sleep(self.pause_seconds)

        return list(products_by_id.values())
