from copy import deepcopy
from datetime import datetime
from decimal import Decimal

import pytest

from backend.scraper_hofer import CATALOG_URL, PAGE_SIZE, HoferAdapter, HoferError, parse_product


@pytest.fixture
def hofer_product():
    return {
        "sku": "000000000000100778",
        "name": "Toast",
        "brandName": "HAPPY HARVEST",
        "urlSlugText": "happy-harvest-toast",
        "notForSale": True,
        "sellingSize": "0,5 kg",
        "sellingUnitDisplay": None,
        "onSaleDate": "2026-09-21",
        "onSaleDateDisplay": "Od ponedeljka, 21. 9.",
        "price": {
            "amount": 233,
            "amountRelevant": 233,
            "amountRelevantDisplay": "2,33\xa0€",
            "wasPriceDisplay": "prej 2,99\xa0€",
            "comparison": 466,
            "comparisonDisplay": "4,66\xa0€/1 kg",
            "perUnit": None,
            "perUnitDisplay": None,
            "currencyCode": "EUR",
        },
        "categories": [
            {
                "id": "1588161418378170",
                "name": "Kruh in pekovski izdelki",
                "urlSlugText": "kruh-in-pek",
            }
        ],
        "assets": [
            {
                "url": "https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/product/png/scaleWidth/{width}/asset/{slug}",
                "maxWidth": 2000,
                "assetType": "FR01",
            }
        ],
        "badges": [{"items": [{"displayText": "AKCIJA"}]}],
    }


def test_parse_product_preserves_sku_and_public_price_semantics(hofer_product):
    product = parse_product(hofer_product, now=datetime(2026, 9, 22))

    assert product.external_id == "000000000000100778"
    assert product.name == "Toast"
    assert product.gtins == ()
    assert product.brand == "HAPPY HARVEST"
    assert product.category == "Kruh in pekovski izdelki"
    assert product.unit == "0,5 kg"
    assert product.url == (
        "https://www.hofer.si/izdelek/happy-harvest-toast-000000000000100778"
    )
    assert product.image_url == (
        "https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/product/png/scaleWidth/600/asset/"
        "happy-harvest-toast"
    )
    assert product.price.effective_price == Decimal("2.33")
    assert product.price.regular_price == Decimal("2.99")
    assert product.price.promotion_price == Decimal("2.33")
    assert product.price.previous_price == Decimal("2.99")
    assert product.price.unit_price == Decimal("4.66")
    assert product.price.unit_base == "1 kg"
    assert product.price.currency == "EUR"
    assert product.price.promotion_starts_at == datetime(2026, 9, 21)
    assert product.price.promotion_ends_at is None
    assert product.price.requires_loyalty is False
    assert product.price.promotion_data["onSaleDate"] == "2026-09-21"


def test_future_hofer_promotion_does_not_replace_current_price(hofer_product):
    product = parse_product(hofer_product, now=datetime(2026, 9, 20))

    assert product.price.effective_price == Decimal("2.99")
    assert product.price.regular_price == Decimal("2.99")
    assert product.price.promotion_price is None
    assert product.price.promotion_type is None
    assert product.price.promotion_starts_at == datetime(2026, 9, 21)


def test_sku_is_never_inferred_as_a_gtin(hofer_product):
    hofer_product["sku"] = "03838975531314"
    hofer_product["ean"] = "3838975531314"
    hofer_product["gtins"] = ["3838975531314"]

    product = parse_product(hofer_product)

    assert product.external_id == "03838975531314"
    assert product.gtins == ()


def _minimal_product(sku: str, name: str | None = None, *, not_for_sale: bool = False):
    return {
        "sku": sku,
        "name": name or f"Product {sku}",
        "urlSlugText": f"product-{sku}",
        "notForSale": not_for_sale,
        "price": {
            "amountRelevant": 125,
            "comparison": None,
            "currencyCode": "EUR",
        },
        "categories": [],
        "assets": [],
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        return FakeResponse(self.pages[params["offset"]])


def _page(offset, total, products):
    return {
        "data": products,
        "meta": {
            "pagination": {
                "offset": offset,
                "limit": PAGE_SIZE,
                "totalCount": total,
            }
        },
    }


def test_fetch_catalog_paginates_deduplicates_and_keeps_not_for_sale():
    first_page = [_minimal_product(f"{index:018d}") for index in range(PAGE_SIZE)]
    duplicate = deepcopy(first_page[0])
    duplicate["name"] = "Updated duplicate"
    duplicate["notForSale"] = True
    session = FakeSession(
        {
            0: _page(0, PAGE_SIZE + 1, first_page),
            PAGE_SIZE: _page(PAGE_SIZE, PAGE_SIZE + 1, [duplicate]),
        }
    )

    products = HoferAdapter(session=session, pause_seconds=0).fetch_catalog()

    assert len(products) == PAGE_SIZE
    assert products[0].external_id == "000000000000000000"
    assert products[0].name == "Updated duplicate"
    assert products[0].gtins == ()
    assert [call[0] for call in session.calls] == [CATALOG_URL, CATALOG_URL]
    assert [call[1]["offset"] for call in session.calls] == [0, PAGE_SIZE]
    assert all(call[1]["limit"] == 60 for call in session.calls)
    assert all(call[1]["servicePoint"] == "I032" for call in session.calls)


def test_fetch_catalog_rejects_total_changes_between_pages():
    first_page = [_minimal_product(f"{index:018d}") for index in range(PAGE_SIZE)]
    session = FakeSession(
        {
            0: _page(0, PAGE_SIZE + 1, first_page),
            PAGE_SIZE: _page(PAGE_SIZE, PAGE_SIZE + 2, [_minimal_product("last")]),
        }
    )

    with pytest.raises(HoferError, match="total changed"):
        HoferAdapter(session=session, pause_seconds=0).fetch_catalog()
