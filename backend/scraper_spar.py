"""SPAR Slovenia anonymous nationwide catalog adapter."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .catalog_import import CatalogProduct, PriceObservation


HOME_URL = "https://online.spar.si/"
GRAPHQL_URL = "https://deadpool.unified-jennet.instaleap.io/api/v3"
CLIENT_ID = "SPAR_SLOVENIA"
DEFAULT_STORE = "81701"
DEFAULT_TIMEOUT = (5, 30)
FOOD_ROOTS = {f"S{number}" for number in range(1, 11)}
DPL_KEY_PATTERN = re.compile(
    r'(?:\\?"dplApiKey\\?"\s*:\s*\\?")([0-9a-f-]{36})(?:\\?")', re.IGNORECASE
)

CATEGORY_QUERY = """
query GetCategory($input: GetCategoryInput!) {
  getCategory(getCategoryInput: $input) {
    reference name hasChildren
    subCategories {
      reference name hasChildren
      subCategories { reference name hasChildren }
    }
  }
}
"""

PRODUCTS_QUERY = """
query GetProductsByCategory($input: GetProductsByCategoryInput!) {
  getProductsByCategory(getProductsByCategoryInput: $input) {
    pagination { page pages total { value relation } }
    category {
      reference name
      products {
        sku ean name slug brand unit subUnit subQty
        price previousPrice pricePerSubUnit promotionPricePerSubUnit
        photosUrl isActive isAvailable
        categoriesData { name reference }
        promotion {
          type description isActive
          conditions { quantity price }
          startDateTime endDateTime
        }
        promotions {
          id type description isActive startDateTime endDateTime
          conditions { field operator value }
          restrictions { field operator value }
          benefit { type value label imagesURL }
        }
      }
    }
  }
}
"""


class SparError(RuntimeError):
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
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "nakupovalni-listek/1.0 (+catalog import)",
            "Origin": HOME_URL.rstrip("/"),
            "Content-Type": "application/json",
        }
    )
    return session


def _decimal(value, required: bool = False) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise SparError("SPAR product is missing its price")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise SparError(f"Invalid SPAR price: {value!r}")
    if not result.is_finite() or result < 0:
        raise SparError(f"Invalid SPAR price: {value!r}")
    return result.quantize(Decimal("0.01"))


def _datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _loyalty_only(promotion: dict) -> bool:
    benefit = promotion.get("benefit") or {}
    text = " ".join(
        str(value)
        for value in (
            promotion.get("type"),
            promotion.get("description"),
            benefit.get("label"),
        )
        if value
    ).lower()
    return "spar plus" in text or "plus kart" in text or "loyalty" in text


def _is_single_unit_promotion(promotion: dict) -> bool:
    for condition in promotion.get("conditions") or []:
        if not isinstance(condition, dict):
            return False
        field = str(condition.get("field") or "").lower()
        if not field and ("quantity" in condition or "qty" in condition):
            field = "quantity"
        if "qty" not in field and "quantity" not in field:
            return False
        try:
            value = condition.get("value", condition.get("quantity", condition.get("qty")))
            if Decimal(str(value)) != 1:
                return False
        except (InvalidOperation, TypeError):
            return False
    return True


def _promotion_list(value) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _promotion_is_current(promotion: dict, now: datetime) -> bool:
    start = _datetime(promotion.get("startDateTime"))
    end = _datetime(promotion.get("endDateTime"))
    if promotion.get("startDateTime") and start is None:
        return False
    if promotion.get("endDateTime") and end is None:
        return False
    return (start is None or start <= now) and (end is None or now <= end)


def parse_product(
    raw: dict,
    category_name: str,
    now: datetime | None = None,
) -> CatalogProduct:
    sku = raw.get("sku")
    name = raw.get("name")
    if sku in (None, "") or not isinstance(name, str) or not name.strip():
        raise SparError("SPAR product is missing sku or name")
    regular_price = _decimal(raw.get("price"), required=True)
    assert regular_price is not None
    public_candidates: list[tuple[Decimal, dict]] = []
    loyalty_candidates: list[dict] = []
    current_time = now or datetime.now(UTC).replace(tzinfo=None)
    if current_time.tzinfo is not None:
        current_time = current_time.astimezone(UTC).replace(tzinfo=None)

    legacy_promotions = _promotion_list(raw.get("promotion"))
    for promotion in legacy_promotions:
        if not promotion.get("isActive") or not _promotion_is_current(promotion, current_time):
            continue
        if promotion.get("restrictions") or not _is_single_unit_promotion(promotion):
            continue
        conditions = promotion.get("conditions") or []
        for condition in conditions:
            quantity = condition.get("quantity", condition.get("qty")) if isinstance(condition, dict) else 0
            if not isinstance(condition, dict) or Decimal(str(quantity or 0)) != 1:
                continue
            price = _decimal(condition.get("price"))
            if price is None:
                continue
            if _loyalty_only(promotion):
                loyalty_candidates.append(promotion)
            else:
                public_candidates.append((price, promotion))

    modern_promotions = _promotion_list(raw.get("promotions") or raw.get("promotionsV2"))
    for promotion in modern_promotions:
        if not promotion.get("isActive") or not _promotion_is_current(promotion, current_time):
            continue
        if promotion.get("restrictions"):
            continue
        benefit = promotion.get("benefit") or {}
        if benefit.get("type") != "unitPrice" or not _is_single_unit_promotion(promotion):
            continue
        price = _decimal(benefit.get("value"))
        if price is None:
            continue
        if _loyalty_only(promotion):
            loyalty_candidates.append(promotion)
        else:
            public_candidates.append((price, promotion))

    effective_price = regular_price
    active_promotion = None
    if public_candidates:
        effective_price, active_promotion = min(public_candidates, key=lambda item: item[0])
    elif loyalty_candidates:
        active_promotion = loyalty_candidates[0]
    all_promotions = legacy_promotions + modern_promotions
    photos = raw.get("photosUrl") or []
    if isinstance(photos, str):
        photos = [photos]
    slug = raw.get("slug")
    unit = raw.get("subUnit") or raw.get("unit")
    if raw.get("subQty") and unit:
        unit = f"{raw['subQty']} {unit}"

    return CatalogProduct(
        external_id=str(sku),
        name=name.strip(),
        gtins=tuple(str(ean) for ean in raw.get("ean") or []),
        brand=str(raw["brand"]) if raw.get("brand") else None,
        category=category_name,
        unit=str(unit) if unit else None,
        url=f"{HOME_URL}p/{slug}" if slug else None,
        image_url=str(photos[0]) if photos else None,
        price=PriceObservation(
            effective_price=effective_price,
            regular_price=regular_price,
            promotion_price=effective_price if effective_price < regular_price else None,
            previous_price=_decimal(raw.get("previousPrice")),
            unit_price=_decimal(
                raw.get("promotionPricePerSubUnit")
                if effective_price < regular_price and raw.get("promotionPricePerSubUnit") is not None
                else raw.get("pricePerSubUnit")
            ),
            unit_base=str(raw.get("subUnit")) if raw.get("subUnit") else None,
            promotion_type=str(active_promotion.get("type")) if active_promotion else None,
            promotion_starts_at=_datetime(active_promotion.get("startDateTime"))
            if active_promotion
            else None,
            promotion_ends_at=_datetime(active_promotion.get("endDateTime"))
            if active_promotion
            else None,
            requires_loyalty=bool(loyalty_candidates and not public_candidates),
            promotion_data=all_promotions or None,
        ),
    )


class SparAdapter:
    retailer_name = "SPAR"
    catalog_is_complete = True

    def __init__(
        self,
        session: requests.Session | None = None,
        store_reference: str = DEFAULT_STORE,
        page_size: int = 100,
        pause_seconds: float = 0.1,
    ):
        self.session = session or build_session()
        self.store_reference = store_reference
        self.page_size = page_size
        self.pause_seconds = pause_seconds

    def _request(self, query: str, variables: dict) -> dict:
        try:
            response = self.session.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables},
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "")[:1000]
            raise SparError(f"SPAR API request failed: {exc}; {detail}") from exc
        except ValueError as exc:
            raise SparError("SPAR API returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("errors"):
            raise SparError(f"SPAR API returned errors: {payload.get('errors') if isinstance(payload, dict) else payload}")
        return payload.get("data") or {}

    def _configure_api_key(self):
        try:
            response = self.session.get(HOME_URL, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SparError(f"SPAR configuration request failed: {exc}") from exc
        match = DPL_KEY_PATTERN.search(response.text)
        if match is None:
            raise SparError("SPAR homepage did not expose a DPL API key")
        self.session.headers["dpl-api-key"] = match.group(1)

    def _food_categories(self) -> list[tuple[str, str]]:
        data = self._request(
            CATEGORY_QUERY,
            {"input": {"clientId": CLIENT_ID, "storeReference": self.store_reference}},
        )
        categories = data.get("getCategory")
        if not isinstance(categories, list):
            raise SparError("SPAR category response has an invalid shape")
        result = [
            (str(category["reference"]), str(category["name"]))
            for category in categories
            if isinstance(category, dict) and category.get("reference") in FOOD_ROOTS
        ]
        if len(result) != len(FOOD_ROOTS):
            raise SparError("SPAR did not return all expected grocery categories")
        return result

    def fetch_catalog(self) -> list[CatalogProduct]:
        self._configure_api_key()
        products_by_sku: dict[str, CatalogProduct] = {}
        for reference, fallback_name in self._food_categories():
            page = 1
            expected_pages = None
            while expected_pages is None or page <= expected_pages:
                data = self._request(
                    PRODUCTS_QUERY,
                    {
                        "input": {
                            "clientId": CLIENT_ID,
                            "storeReference": self.store_reference,
                            "categoryReference": reference,
                            "currentPage": page,
                            "pageSize": self.page_size,
                        }
                    },
                )
                result = data.get("getProductsByCategory")
                if not isinstance(result, dict):
                    raise SparError("SPAR product response has an invalid shape")
                pagination = result.get("pagination") or {}
                try:
                    pages = int(pagination["pages"])
                except (KeyError, TypeError, ValueError):
                    raise SparError("SPAR product pagination is invalid")
                if expected_pages is not None and pages != expected_pages:
                    raise SparError("SPAR product total changed during pagination")
                expected_pages = pages
                category = result.get("category") or {}
                raw_products = category.get("products")
                if not isinstance(raw_products, list):
                    raise SparError("SPAR product page has an invalid shape")
                category_name = str(category.get("name") or fallback_name)
                for raw_product in raw_products:
                    if not isinstance(raw_product, dict):
                        raise SparError("SPAR product page contains a non-object product")
                    if raw_product.get("isActive") is False or raw_product.get("isAvailable") is False:
                        continue
                    product = parse_product(raw_product, category_name)
                    products_by_sku[product.external_id] = product
                page += 1
                if self.pause_seconds and page <= expected_pages:
                    time.sleep(self.pause_seconds)
        return list(products_by_sku.values())
