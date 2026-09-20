from copy import deepcopy
from decimal import Decimal

import pytest

from backend.scraper_tus import (
    DEFAULT_STORE_ID,
    TusAdapter,
    TusError,
    aggregate_products,
    parse_category_pairs,
    parse_product,
    product_page_items,
    select_stores,
    source_external_id,
)


@pytest.fixture
def celje_store():
    return {"storeId": "5861", "storeName": "Planet Tuš Celje", "hidden": None}


@pytest.fixture
def ljubljana_store():
    return {"storeId": "5994", "storeName": "Tuš BTC Ljubljana", "hidden": None}


@pytest.fixture
def regular_product():
    return {
        "id": "321755",
        "itemId": None,
        "EAN": "4034900004932",
        "name": "Maslo Meggle 250 g",
        "brand": "MEGGLE",
        "price": 4.69,
        "discountedPrice": None,
        "promotionDisplayPrice": None,
        "priceEm": 18.76,
        "em": "KG",
        "weight": 0.25,
        "inStock": True,
        "percDiscount": None,
        "badges": [],
        "img": None,
        "gratisPromo": None,
    }


def test_parses_catalog_fields_and_filters_out_of_stock(regular_product, celje_store):
    parsed = parse_product(
        regular_product,
        "Hlajeni in mlečni izdelki",
        "Masla",
        celje_store,
    )

    assert parsed is not None
    assert parsed.external_id == source_external_id("321755", "4034900004932")
    assert parsed.name == "Maslo Meggle 250 g"
    assert parsed.gtins == ("4034900004932",)
    assert parsed.brand == "MEGGLE"
    assert parsed.category == "Hlajeni in mlečni izdelki / Masla"
    assert parsed.url == "https://hitrinakup.com/izdelki/321755"
    assert parsed.image_url.endswith("/remote_images/items_images/4034900004932.jpg")
    assert parsed.price.effective_price == Decimal("4.69")
    assert parsed.price.regular_price == Decimal("4.69")
    assert parsed.price.unit_price == Decimal("18.76")
    assert parsed.price.unit_base == "KG"
    assert parsed.price.requires_loyalty is False

    unavailable = deepcopy(regular_product)
    unavailable["inStock"] = False
    assert parse_product(unavailable, "Hlajeni in mlečni izdelki", "Masla", celje_store) is None


def test_same_bundle_id_with_different_eans_remains_two_products(celje_store):
    first = {
        "id": "BUN758597",
        "EAN": "3830000427269",
        "name": "Ora, sočni eksotik, 24 x 0,33 l",
        "price": 21.36,
        "discountedPrice": 12.96,
        "promotionDisplayPrice": None,
        "priceEm": 1.64,
        "em": "L",
        "inStock": True,
    }
    second = {**first, "EAN": "3830065024454"}

    products = aggregate_products(
        [
            parse_product(first, "Brezalkoholne pijače", "Gazirane pijače", celje_store),
            parse_product(second, "Brezalkoholne pijače", "Gazirane pijače", celje_store),
        ]
    )

    assert len(products) == 2
    assert {product.gtins for product in products} == {
        ("3830000427269",),
        ("3830065024454",),
    }
    assert len({product.external_id for product in products}) == 2


def test_promotion_display_price_precedes_discounted_and_regular(regular_product, celje_store):
    raw = {
        **regular_product,
        "price": 5.0,
        "discountedPrice": 4.0,
        "promotionDisplayPrice": 3.5,
        "percDiscount": 30,
        "gratisPromo": "BUY_TWO",
        "gratisMinItems": 2,
        "gratisFreeItems": 1,
        "gratisIsCombo": True,
    }

    parsed = parse_product(raw, "Hlajeni in mlečni izdelki", "Masla", celje_store)

    assert parsed is not None
    assert parsed.price.effective_price == Decimal("3.50")
    assert parsed.price.regular_price == Decimal("5.00")
    assert parsed.price.promotion_price == Decimal("3.50")
    assert parsed.price.promotion_type == "sponsored"
    offer = parsed.price.promotion_data["offers"][0]
    assert offer["promotion_display_price"] == "3.50"
    assert offer["discounted_price"] == "4.00"
    assert offer["gratis_promo"] == "BUY_TWO"
    assert offer["gratis_is_combo"] is True


def test_cross_store_offers_aggregate_to_lowest_anonymous_price(
    regular_product,
    celje_store,
    ljubljana_store,
):
    celje_raw = {
        **regular_product,
        "price": 5.0,
        "discountedPrice": 4.0,
    }
    ljubljana_raw = {
        **regular_product,
        "price": 5.5,
        "discountedPrice": None,
        "promotionDisplayPrice": 3.5,
        "priceEm": 14.0,
    }
    celje = parse_product(celje_raw, "Hlajeni in mlečni izdelki", "Masla", celje_store)
    ljubljana = parse_product(
        ljubljana_raw,
        "Hlajeni in mlečni izdelki",
        "Masla",
        ljubljana_store,
    )

    products = aggregate_products([celje, ljubljana])

    assert len(products) == 1
    product = products[0]
    assert product.price.effective_price == Decimal("3.50")
    assert product.price.regular_price == Decimal("5.50")
    assert product.price.unit_price == Decimal("14.00")
    offers = product.price.promotion_data["offers"]
    assert {offer["store_id"] for offer in offers} == {"5861", "5994"}
    assert {offer["effective_price"] for offer in offers} == {"4.00", "3.50"}


def test_category_and_store_fixtures_select_second_level_grocery_pairs():
    categories = [
        {
            "name": "Brezalkoholne pijače",
            "children": [
                {"name": "Gazirane pijače", "children": [{"name": "Cole"}]},
                {"name": "Vode", "children": []},
            ],
        },
        {"name": "Storitve in ostalo", "children": [{"name": "Darilne kartice"}]},
    ]
    stores = [
        {"storeId": "5861", "storeName": "Celje", "hidden": None},
        {"storeId": "5994", "storeName": "Ljubljana", "hidden": False},
        {"storeId": "hidden", "storeName": "Hidden", "hidden": True},
    ]

    assert parse_category_pairs(categories) == [
        ("Brezalkoholne pijače", "Gazirane pijače"),
        ("Brezalkoholne pijače", "Vode"),
    ]
    assert [store["storeId"] for store in select_stores(stores)] == ["5861", "5994"]
    assert [store["storeId"] for store in select_stores(stores, ["5994"])] == ["5994"]


def test_adapter_defaults_to_the_reference_store():
    adapter = TusAdapter(session=object())

    assert adapter.store_ids == (DEFAULT_STORE_ID,)


def test_null_product_page_is_rejected_as_incomplete():
    with pytest.raises(TusError, match="missing"):
        product_page_items(None, "test category")
    with pytest.raises(TusError, match="invalid shape"):
        product_page_items({"items": None}, "test category")
