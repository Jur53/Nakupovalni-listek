"""Tuš Hitri Nakup anonymous catalog adapter."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import quote
from uuid import uuid4

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .catalog_import import CatalogProduct, PriceObservation


BASE_URL = "https://hitrinakup.com"
GRAPHQL_URL = f"{BASE_URL}/graphql"
CONFIG_URL = f"{BASE_URL}/api/config"
DEFAULT_TIMEOUT = (5, 30)
DEFAULT_PAGE_SIZE = 1000
DEFAULT_STORE_ID = "5861"
FRONTEND_VERSION = "0.4.34"
EXCLUDED_TOP_CATEGORIES = {"Storitve in ostalo"}

API_VERSION_QUERY = """
query getApiVersion {
  getApiVersion
}
"""

CREATE_SESSION_MUTATION = """
mutation createSession(
  $userId: String!
  $uri: String!
  $agent: String!
  $url: String
  $prevSessionId: String
  $code: String
  $version: String
) {
  createSession(
    userId: $userId
    uri: $uri
    agent: $agent
    url: $url
    prevSessionId: $prevSessionId
    code: $code
    version: $version
  ) {
    id
    date
    agent
  }
}
"""

STORES_QUERY = """
query getStores {
  getStores {
    storeName
    storeId
    hidden
    defaultStore
    city
    zip
    locations {
      id
      locationName
      delivery
      isPrimary
      showDefault
    }
  }
}
"""

CATEGORIES_QUERY = """
query getCategories($userId: String, $limit: Int, $cypherQuery: String) {
  getCategories(userId: $userId, limit: $limit, cypherQuery: $cypherQuery) {
    name
    key
    image
    children {
      name
      key
      children { name key }
    }
  }
}
"""

PRODUCTS_QUERY = """
query getItemsForSelectedSubCategory(
  $categoriesLimit: Int
  $categoriesSkip: Int
  $categoryName: String
  $cypherQuery: String
  $date: String
  $filterProperties: [FilterCategoryDataInput]
  $sorting: String
  $storeId: String
  $subcategoryName: String
) {
  getItemsForSelectedSubCategory(
    categoriesLimit: $categoriesLimit
    categoriesSkip: $categoriesSkip
    categoryName: $categoryName
    cypherQuery: $cypherQuery
    date: $date
    filterProperties: $filterProperties
    sorting: $sorting
    storeId: $storeId
    subcategoryName: $subcategoryName
  ) {
    items {
      weighing
      weight
      itemId
      EAN
      name
      orderLimit
      price
      discountedPrice
      lowQuantity
      promotionDisplayPrice
      alcohol
      group
      quantity
      itemWeighingChangeQuantityStep
      inStock
      priceEm
      em
      badges
      type
      comment
      discountEan
      id
      displayName
      itemBackground
      bannerColor
      bannerTextBold
      bannerTextNormal
      bannerTextColor
      img
      favourite
      brand
      category
      monetisationId
      monetisationName
      percDiscount
      gratisPromo
      gratisMinItems
      gratisFreeItems
      gratisIsCombo
    }
  }
}
"""


class TusError(RuntimeError):
    pass


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": "nakupovalni-listek/1.0 (+catalog import)",
            "Origin": BASE_URL,
        }
    )
    return session


def _decimal(value, required: bool = False) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise TusError("Tuš product is missing its regular price")
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise TusError(f"Invalid Tuš price: {value!r}")
    if not result.is_finite() or result < 0:
        raise TusError(f"Invalid Tuš price: {value!r}")
    return result.quantize(Decimal("0.01"))


def _json_safe(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _money(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _js_date_string(value: date | datetime | str | None) -> str:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("catalog_date cannot be empty")
        return value.strip()
    selected = value.date() if isinstance(value, datetime) else value or date.today()
    weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return (
        f"{weekdays[selected.weekday()]} {months[selected.month - 1]} "
        f"{selected.day:02d} {selected.year}"
    )


def source_external_id(source_id: str, ean: str | None) -> str:
    """Encode the exact Tuš (id, EAN) source identity without ambiguity."""
    return json.dumps([source_id, ean], ensure_ascii=False, separators=(",", ":"))


def parse_category_pairs(categories) -> list[tuple[str, str]]:
    if not isinstance(categories, list):
        raise TusError("Tuš category response has an invalid shape")
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for category in categories:
        if not isinstance(category, dict):
            raise TusError("Tuš category response contains a non-object category")
        category_name = category.get("name")
        if not isinstance(category_name, str) or not category_name.strip():
            raise TusError("Tuš category is missing its name")
        category_name = category_name.strip()
        if category_name in EXCLUDED_TOP_CATEGORIES:
            continue
        children = category.get("children") or []
        if not isinstance(children, list):
            raise TusError("Tuš category children have an invalid shape")
        for child in children:
            name = child.get("name") if isinstance(child, dict) else None
            if not isinstance(name, str) or not name.strip():
                raise TusError("Tuš subcategory is missing its name")
            pair = (category_name, name.strip())
            if pair not in seen:
                pairs.append(pair)
                seen.add(pair)
    if not pairs:
        raise TusError("Tuš returned no grocery category pairs")
    return pairs


def select_stores(stores, requested_ids: Iterable[str] | None = None) -> list[dict]:
    if not isinstance(stores, list):
        raise TusError("Tuš store response has an invalid shape")
    available: dict[str, dict] = {}
    for store in stores:
        if not isinstance(store, dict):
            raise TusError("Tuš store response contains a non-object store")
        store_id = store.get("storeId")
        if store_id in (None, ""):
            raise TusError("Tuš store is missing storeId")
        if store.get("hidden") is True:
            continue
        available[str(store_id)] = store
    if requested_ids is None:
        selected = list(available.values())
    else:
        requested = list(dict.fromkeys(str(store_id) for store_id in requested_ids))
        missing = [store_id for store_id in requested if store_id not in available]
        if missing:
            raise TusError(f"Unknown or hidden Tuš stores: {', '.join(missing)}")
        selected = [available[store_id] for store_id in requested]
    if not selected:
        raise TusError("Tuš returned no selectable stores")
    return selected


def parse_product(
    raw: dict,
    category_name: str,
    subcategory_name: str,
    store: dict,
) -> CatalogProduct | None:
    if not isinstance(raw, dict):
        raise TusError("Tuš product row is not an object")
    if raw.get("inStock") is False:
        return None
    source_value = raw.get("id")
    name = raw.get("name")
    store_value = store.get("storeId")
    if source_value in (None, "") or not isinstance(name, str) or not name.strip():
        raise TusError("Tuš product is missing id or name")
    if store_value in (None, ""):
        raise TusError("Tuš offer is missing storeId")

    source_id = str(source_value).strip()
    ean_value = raw.get("EAN")
    ean = str(ean_value).strip() if ean_value not in (None, "") else None
    regular_price = _decimal(raw.get("price"), required=True)
    sponsored_price = _decimal(raw.get("promotionDisplayPrice"))
    discounted_price = _decimal(raw.get("discountedPrice"))
    assert regular_price is not None

    if sponsored_price is not None:
        effective_price = sponsored_price
        promotion_type = "sponsored"
    elif discounted_price is not None:
        effective_price = discounted_price
        promotion_type = "discount"
    else:
        effective_price = regular_price
        promotion_type = "gratis" if raw.get("gratisPromo") else None

    unit_base = str(raw["em"]) if raw.get("em") else None
    weight = raw.get("weight")
    unit = f"{weight} {unit_base}" if weight not in (None, "") and unit_base else unit_base
    if ean:
        image_url = f"{BASE_URL}/remote_images/items_images/{quote(ean, safe='')}.jpg"
    else:
        image_url = None

    offer = {
        "store_id": str(store_value),
        "store_name": str(store.get("storeName")) if store.get("storeName") else None,
        "category": category_name,
        "subcategory": subcategory_name,
        "effective_price": _money(effective_price),
        "regular_price": _money(regular_price),
        "promotion_display_price": _money(sponsored_price),
        "discounted_price": _money(discounted_price),
        "unit_price": _money(_decimal(raw.get("priceEm"))),
        "unit_base": unit_base,
        "perc_discount": _json_safe(raw.get("percDiscount")),
        "discount_ean": _json_safe(raw.get("discountEan")),
        "badges": _json_safe(raw.get("badges") or []),
        "gratis_promo": _json_safe(raw.get("gratisPromo")),
        "gratis_min_items": _json_safe(raw.get("gratisMinItems")),
        "gratis_free_items": _json_safe(raw.get("gratisFreeItems")),
        "gratis_is_combo": _json_safe(raw.get("gratisIsCombo")),
        "monetisation_id": _json_safe(raw.get("monetisationId")),
        "monetisation_name": _json_safe(raw.get("monetisationName")),
    }
    promotion_data = {
        "source_identity": [source_id, ean],
        "offers": [offer],
    }
    return CatalogProduct(
        external_id=source_external_id(source_id, ean),
        name=name.strip(),
        gtins=(ean,) if ean else (),
        brand=str(raw["brand"]) if raw.get("brand") else None,
        category=f"{category_name} / {subcategory_name}",
        unit=unit,
        url=f"{BASE_URL}/izdelki/{quote(source_id, safe='')}",
        image_url=image_url,
        price=PriceObservation(
            effective_price=effective_price,
            regular_price=regular_price,
            promotion_price=effective_price if promotion_type in {"sponsored", "discount"} else None,
            unit_price=_decimal(raw.get("priceEm")),
            unit_base=unit_base,
            promotion_type=promotion_type,
            requires_loyalty=False,
            promotion_data=promotion_data,
        ),
    )


def _identity_and_offers(product: CatalogProduct) -> tuple[tuple[str, str | None], list[dict]]:
    data = product.price.promotion_data
    if not isinstance(data, dict):
        raise TusError("Tuš product is missing aggregation metadata")
    identity = data.get("source_identity")
    offers = data.get("offers")
    if (
        not isinstance(identity, list)
        or len(identity) != 2
        or not isinstance(identity[0], str)
        or identity[1] is not None and not isinstance(identity[1], str)
        or not isinstance(offers, list)
        or any(not isinstance(offer, dict) for offer in offers)
    ):
        raise TusError("Tuš product has invalid aggregation metadata")
    return (identity[0], identity[1]), offers


def _merge_products(left: CatalogProduct, right: CatalogProduct) -> CatalogProduct:
    left_identity, left_offers = _identity_and_offers(left)
    right_identity, right_offers = _identity_and_offers(right)
    if left_identity != right_identity:
        raise TusError("Cannot merge different Tuš source products")

    winner = right if right.price.effective_price < left.price.effective_price else left
    offers_by_store: dict[str, dict] = {}
    for offer in [*left_offers, *right_offers]:
        store_id = str(offer.get("store_id") or "")
        if not store_id:
            raise TusError("Tuš aggregation offer is missing store_id")
        current = offers_by_store.get(store_id)
        if current is None:
            offers_by_store[store_id] = offer
            continue
        current_price = _decimal(current.get("effective_price"), required=True)
        candidate_price = _decimal(offer.get("effective_price"), required=True)
        if candidate_price is not None and current_price is not None and candidate_price < current_price:
            offers_by_store[store_id] = offer

    promotion_data = {
        "source_identity": [left_identity[0], left_identity[1]],
        "offers": list(offers_by_store.values()),
    }
    return replace(
        winner,
        price=replace(winner.price, promotion_data=promotion_data),
    )


def aggregate_products(products: Iterable[CatalogProduct]) -> list[CatalogProduct]:
    aggregated: dict[tuple[str, str | None], CatalogProduct] = {}
    for product in products:
        identity, _ = _identity_and_offers(product)
        current = aggregated.get(identity)
        aggregated[identity] = product if current is None else _merge_products(current, product)
    return list(aggregated.values())


def product_page_items(result, context: str) -> list[dict]:
    if result is None:
        raise TusError(f"Tuš product page is missing for {context}")
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise TusError(f"Tuš product page has an invalid shape for {context}: {result!r}")
    if any(not isinstance(item, dict) for item in result["items"]):
        raise TusError(f"Tuš product page contains a non-object item for {context}")
    return result["items"]


class TusAdapter:
    retailer_name = "Tuš"
    catalog_is_complete = True

    def __init__(
        self,
        session: requests.Session | None = None,
        store_ids: Iterable[str] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        pause_seconds: float = 0.25,
        catalog_date: date | datetime | str | None = None,
    ):
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if pause_seconds < 0:
            raise ValueError("pause_seconds cannot be negative")
        if store_ids is None:
            store_ids = [DEFAULT_STORE_ID]
        elif isinstance(store_ids, str):
            store_ids = [store_ids]
        self.session = session or build_session()
        self.store_ids = tuple(dict.fromkeys(str(value) for value in store_ids))
        if not self.store_ids:
            raise ValueError("store_ids cannot be empty")
        self.page_size = page_size
        self.pause_seconds = pause_seconds
        self.catalog_date = _js_date_string(catalog_date)
        self.user_id = str(uuid4())
        self.api_version: str | None = None
        self.session_id: str | None = None

    def _graphql(
        self,
        query: str,
        variables: dict | None = None,
        operation_name: str | None = None,
        require_session: bool = True,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_version:
            headers["apiVersion"] = self.api_version
        if require_session:
            if not self.session_id:
                raise TusError("Tuš anonymous session has not been created")
            headers["sessionId"] = self.session_id
        payload = {"query": query, "variables": variables or {}}
        if operation_name:
            payload["operationName"] = operation_name
        try:
            response = self.session.post(
                GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "")[:1000]
            raise TusError(f"Tuš GraphQL request failed: {exc}; {detail}") from exc
        except ValueError as exc:
            raise TusError("Tuš GraphQL returned invalid JSON") from exc
        if not isinstance(body, dict) or body.get("errors"):
            errors = body.get("errors") if isinstance(body, dict) else body
            raise TusError(f"Tuš GraphQL returned errors: {errors}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise TusError("Tuš GraphQL response is missing data")
        return data

    def _bootstrap_session(self):
        data = self._graphql(
            API_VERSION_QUERY,
            operation_name="getApiVersion",
            require_session=False,
        )
        api_version = data.get("getApiVersion")
        if not isinstance(api_version, str) or not api_version:
            raise TusError("Tuš did not return an API version")
        self.api_version = api_version
        data = self._graphql(
            CREATE_SESSION_MUTATION,
            {
                "userId": self.user_id,
                "uri": "hitrinakup.com",
                "agent": self.session.headers.get("User-Agent", "nakupovalni-listek/1.0"),
                "url": f"{BASE_URL}/",
                "prevSessionId": None,
                "code": None,
                "version": FRONTEND_VERSION,
            },
            operation_name="createSession",
            require_session=False,
        )
        created = data.get("createSession")
        if not isinstance(created, dict) or not created.get("id"):
            raise TusError("Tuš did not create an anonymous session")
        self.session_id = str(created["id"])

    def _page_config(self, page_name: str, store_id: str) -> dict:
        try:
            response = self.session.post(
                CONFIG_URL,
                data=json.dumps(
                    {"pageName": page_name, "storeId": store_id, "uri": "hitrinakup.com"}
                ),
                headers={"Content-Type": "text/plain;charset=UTF-8"},
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "")[:1000]
            raise TusError(f"Tuš configuration request failed: {exc}; {detail}") from exc
        except ValueError as exc:
            raise TusError("Tuš configuration endpoint returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TusError("Tuš configuration response has an invalid shape")
        return payload

    @staticmethod
    def _cypher_query(config: dict, operation_name: str, widget_name: str) -> str:
        pending = list(config.get("widgets") or [])
        while pending:
            widget = pending.pop(0)
            if not isinstance(widget, dict):
                continue
            pending.extend(item for item in widget.get("widgets") or [] if isinstance(item, dict))
            query_text = widget.get("query")
            matches = (
                widget.get("queryName") == operation_name
                or widget.get("name") == widget_name
                or isinstance(query_text, str) and operation_name in query_text
            )
            if matches and widget.get("cypherQuery"):
                return str(widget["cypherQuery"])
        raise TusError(f"Tuš configuration did not provide {operation_name} cypherQuery")

    def _stores(self) -> list[dict]:
        data = self._graphql(STORES_QUERY, operation_name="getStores")
        return select_stores(data.get("getStores"), self.store_ids)

    def _category_pairs(self, cypher_query: str) -> list[tuple[str, str]]:
        data = self._graphql(
            CATEGORIES_QUERY,
            {"userId": self.user_id, "limit": 0, "cypherQuery": cypher_query},
            operation_name="getCategories",
        )
        return parse_category_pairs(data.get("getCategories"))

    def fetch_catalog(self) -> list[CatalogProduct]:
        self._bootstrap_session()
        stores = self._stores()
        config_store_id = str(stores[0]["storeId"])
        category_cypher = self._cypher_query(
            self._page_config("categories", config_store_id),
            "getCategories",
            "categories",
        )
        products_cypher = self._cypher_query(
            self._page_config("subcategory_items", config_store_id),
            "getItemsForSelectedSubCategory",
            "all_items_single_subcategory",
        )
        category_pairs = self._category_pairs(category_cypher)
        aggregated: dict[tuple[str, str | None], CatalogProduct] = {}

        for store in stores:
            store_id = str(store["storeId"])
            for category_name, subcategory_name in category_pairs:
                offset = 0
                while True:
                    data = self._graphql(
                        PRODUCTS_QUERY,
                        {
                            "categoriesLimit": self.page_size,
                            "categoriesSkip": offset,
                            "categoryName": category_name,
                            "cypherQuery": products_cypher,
                            "date": self.catalog_date,
                            "filterProperties": [],
                            "sorting": "Priporočeni",
                            "storeId": store_id,
                            "subcategoryName": subcategory_name,
                        },
                        operation_name="getItemsForSelectedSubCategory",
                    )
                    result = data.get("getItemsForSelectedSubCategory")
                    raw_items = product_page_items(
                        result,
                        f"store {store_id}, {category_name} / {subcategory_name}",
                    )
                    for raw in raw_items:
                        product = parse_product(raw, category_name, subcategory_name, store)
                        if product is None:
                            continue
                        identity, _ = _identity_and_offers(product)
                        current = aggregated.get(identity)
                        aggregated[identity] = (
                            product if current is None else _merge_products(current, product)
                        )
                    if self.pause_seconds:
                        time.sleep(self.pause_seconds)
                    if len(raw_items) < self.page_size:
                        break
                    offset += len(raw_items)
        return list(aggregated.values())
