from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.scraper_lidl import ACCEPT_HEADER, LidlAdapter, LidlError, parse_product


NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


@pytest.fixture
def lidl_item():
    return {
        "code": "11000429",
        "gridbox": {
            "productId": 11000429,
            "meta": {"ean": "20601768", "fullTitle": "Fallback title"},
            "data": {
                "erpNumber": "11000429",
                "fullTitle": "ALESTO Dateljni",
                "brand": {"name": "ALESTO"},
                "canonicalUrl": "/p/alesto-dateljni/p11000429",
                "image": "https://www.lidl.si/assets/dates.png",
                "keyfacts": {
                    "wonCategoryPrimary": "Hrana/Sladkarije/Piskoti",
                },
                "regionsV2": {
                    "1": {"isDefault": True, "regionPriceId": "default-price"},
                    "2": {"isDefault": False, "regionPriceId": "other-price"},
                },
                "regionsPrices": {
                    "default-price": {
                        "currentPrice": {
                            "price": 0.79,
                            "oldPrice": 1.09,
                            "currencyCode": "EUR",
                            "startDate": "2026-09-11T10:57:51.630Z",
                            "endDate": "2026-09-27T21:59:59Z",
                            "endDateExclusive": "2026-09-27T22:00:00Z",
                            "basePrice": {"text": "1 kg = 3,16"},
                            "packaging": {"text": "250 g"},
                            "discount": {
                                "deletedPrice": 1.09,
                                "percentageDiscount": 27,
                                "showDiscount": True,
                            },
                        },
                        "currentLidlPlusPrice": {
                            "price": {
                                "price": 0.59,
                                "startDate": "2026-09-18T00:00:00Z",
                                "endDate": "2026-09-21T00:00:00Z",
                            },
                            "lidlPlusText": "z Lidl Plus",
                        },
                        "futureLidlPlusPrices": [{"price": {"price": 0.49}}],
                    },
                    "other-price": {"currentPrice": {"price": 99}},
                },
            },
        },
    }


def test_parse_product_uses_active_public_price_and_metadata(lidl_item):
    product = parse_product(lidl_item, now=NOW)

    assert product is not None
    assert product.external_id == "11000429"
    assert product.name == "ALESTO Dateljni"
    assert product.gtins == ("20601768",)
    assert product.brand == "ALESTO"
    assert product.category == "Hrana/Sladkarije/Piskoti"
    assert product.unit == "250 g"
    assert product.url == "https://www.lidl.si/p/alesto-dateljni/p11000429"
    assert product.image_url == "https://www.lidl.si/assets/dates.png"
    assert product.price.effective_price == Decimal("0.79")
    assert product.price.regular_price == Decimal("1.09")
    assert product.price.promotion_price == Decimal("0.79")
    assert product.price.unit_price == Decimal("3.16")
    assert product.price.unit_base == "1 kg"
    assert product.price.requires_loyalty is False
    assert product.price.promotion_data["currentLidlPlusPrice"]["price"]["price"] == 0.59


def test_lidl_plus_price_never_replaces_public_price(lidl_item):
    product = parse_product(lidl_item, now=NOW)
    assert product is not None
    assert product.price.effective_price == Decimal("0.79")

    del lidl_item["gridbox"]["data"]["regionsPrices"]["default-price"]["currentPrice"]
    assert parse_product(lidl_item, now=NOW) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("startDate", "2026-09-20T00:00:00Z"),
        ("endDateExclusive", "2026-09-19T11:59:59Z"),
    ],
)
def test_skips_inactive_public_prices(lidl_item, field, value):
    current = lidl_item["gridbox"]["data"]["regionsPrices"]["default-price"]["currentPrice"]
    current[field] = value
    assert parse_product(lidl_item, now=NOW) is None


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
        self.headers = {"Accept": ACCEPT_HEADER}

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        return FakeResponse(self.pages[params["offset"]])


def test_fetch_catalog_paginates_and_deduplicates(lidl_item):
    second = deepcopy(lidl_item)
    second["code"] = "11000430"
    second["gridbox"]["data"]["fullTitle"] = "Second product"
    second["gridbox"]["meta"]["ean"] = "invalid"
    second["gridbox"]["data"]["erpNumber"] = "11000430"

    third = deepcopy(lidl_item)
    third["code"] = "11000431"
    third["gridbox"]["data"]["fullTitle"] = "Third product"
    third["gridbox"]["data"]["erpNumber"] = "11000431"

    pages = {
        0: {"numFound": 4, "offset": 0, "fetchsize": 2, "items": [lidl_item, second]},
        2: {"numFound": 4, "offset": 2, "fetchsize": 2, "items": [deepcopy(second), third]},
    }
    session = FakeSession(pages)
    products = LidlAdapter(session=session, page_size=2, pause_seconds=0, now=NOW).fetch_catalog()

    assert [product.external_id for product in products] == ["11000429", "11000430", "11000431"]
    assert products[1].gtins == ()
    assert [call[1]["offset"] for call in session.calls] == [0, 2]
    assert all(call[1]["fetchsize"] == 2 for call in session.calls)


def test_fetch_catalog_rejects_total_changes_between_pages(lidl_item):
    pages = {
        0: {"numFound": 4, "offset": 0, "fetchsize": 2, "items": [lidl_item, lidl_item]},
        2: {"numFound": 2, "offset": 2, "fetchsize": 2, "items": [lidl_item]},
    }

    with pytest.raises(LidlError, match="total changed"):
        LidlAdapter(
            session=FakeSession(pages),
            page_size=2,
            pause_seconds=0,
            now=NOW,
        ).fetch_catalog()
