from datetime import datetime
from decimal import Decimal

from backend.scraper_mercator import _mercator_catalog_product
from backend.scraper_spar import parse_product


def test_mercator_public_and_loyalty_price_semantics():
    raw = {
        "url": "/izdelek/1/test",
        "mainImageSrc": "https://mercatoronline.si/image.jpg",
        "data": {
            "cinv": "1",
            "name": "Test",
            "current_price": "1.50",
            "normal_price": "2.00",
            "pc30_price": "1.75",
            "price_per_unit": "3.00",
            "price_per_unit_base": "1kg",
            "gtins": [{"gtin": "3838975531314"}],
            "discounts": [{"group_type": "discount", "valid_from": "20260918000000"}],
        },
    }
    public = _mercator_catalog_product(raw, now=datetime(2026, 9, 19))
    assert public.price.effective_price == Decimal("1.50")
    assert public.price.promotion_price == Decimal("1.50")
    assert public.price.requires_loyalty is False

    raw["data"]["discounts"][0]["clubs"] = "Pika"
    loyalty = _mercator_catalog_product(raw, now=datetime(2026, 9, 19))
    assert loyalty.price.effective_price == Decimal("2.00")
    assert loyalty.price.promotion_price is None
    assert loyalty.price.requires_loyalty is True


def test_spar_applies_only_public_single_unit_promotions():
    raw = {
        "sku": "123",
        "ean": ["8052575091176"],
        "name": "SPAR Test",
        "price": 4.0,
        "pricePerSubUnit": 8.0,
        "promotion": [
            {
                "isActive": True,
                "type": "bundle",
                "conditions": [{"quantity": 2, "price": 3.0}],
            },
            {
                "isActive": True,
                "type": "discount",
                "conditions": [{"quantity": 1, "price": 3.5}],
            },
        ],
        "promotions": [],
    }
    parsed = parse_product(raw, "Food")
    assert parsed.price.regular_price == Decimal("4.00")
    assert parsed.price.effective_price == Decimal("3.50")
    assert parsed.price.promotion_price == Decimal("3.50")
    assert len(parsed.price.promotion_data) == 2

    raw["promotion"] = raw["promotion"][1]
    parsed_single = parse_product(raw, "Food")
    assert parsed_single.price.effective_price == Decimal("3.50")


def test_spar_ignores_restricted_and_future_promotions():
    raw = {
        "sku": "restricted",
        "name": "SPAR Test",
        "price": 4,
        "ean": [],
        "promotions": [
            {
                "isActive": True,
                "type": "discount",
                "startDateTime": "2026-09-01T00:00:00Z",
                "endDateTime": "2026-09-30T00:00:00Z",
                "conditions": [{"field": "quantity", "value": 1}],
                "restrictions": [{"field": "channel", "value": "member"}],
                "benefit": {"type": "unitPrice", "value": 2},
            },
            {
                "isActive": True,
                "type": "discount",
                "startDateTime": "2026-10-01T00:00:00Z",
                "conditions": [{"field": "quantity", "value": 1}],
                "restrictions": [],
                "benefit": {"type": "unitPrice", "value": 1},
            },
        ],
    }

    parsed = parse_product(raw, "Food", now=datetime(2026, 9, 19))

    assert parsed.price.effective_price == Decimal("4.00")
    assert parsed.price.promotion_price is None
    assert parsed.price.promotion_data == raw["promotions"]


def test_mercator_ignores_inactive_promotions_and_keeps_selected_metadata():
    raw = {
        "url": "/izdelek/1/test",
        "mainImageSrc": "https://mercatoronline.si/image.jpg",
        "data": {
            "cinv": "1",
            "name": "Test",
            "current_price": "1.00",
            "normal_price": "4.00",
            "discounts": [
                {
                    "group_type": "future",
                    "discount_price": "1.00",
                    "valid_from": "20261001000000",
                },
                {
                    "group_type": "current-high",
                    "discount_price": "3.00",
                    "valid_from": "20260901000000",
                    "valid_to": "20260930000000",
                },
                {
                    "group_type": "current-low",
                    "discount_price": "2.50",
                    "valid_from": "20260901000000",
                    "valid_to": "20260930000000",
                },
            ],
        },
    }

    parsed = _mercator_catalog_product(raw, now=datetime(2026, 9, 19))

    assert parsed.price.effective_price == Decimal("2.50")
    assert parsed.price.promotion_type == "current-low"
    assert parsed.price.promotion_starts_at == datetime(2026, 9, 1)


def test_spar_rejects_non_quantity_conditions():
    raw = {
        "sku": "coupon",
        "name": "SPAR Coupon Test",
        "price": 4,
        "ean": [],
        "promotions": [
            {
                "isActive": True,
                "type": "discount",
                "conditions": [{"field": "coupon", "value": "SAVE"}],
                "benefit": {"type": "unitPrice", "value": 2},
            }
        ],
    }

    parsed = parse_product(raw, "Food", now=datetime(2026, 9, 19))

    assert parsed.price.effective_price == Decimal("4.00")
