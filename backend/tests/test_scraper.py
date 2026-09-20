from datetime import date
from decimal import Decimal

import pytest
import requests
from sqlalchemy import func, select

from backend.models import Cena, Izdelek, RetailerProduct, Trgovina
from backend.scraper_mercator import (
    DEFAULT_TIMEOUT,
    ScraperError,
    build_session,
    dobi_izdelke_kategorija,
    dobi_vse_izdelke_kategorija,
    persist_catalog,
    pretvori_izdelek,
)


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status
        self.text = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def raw_product(external_id, total=1, url="/izdelek"):
    return {
        "total": total,
        "url": url,
        "data": {
            "name": f"Product {external_id}",
            "current_price": "1,23 EUR",
            "cinv": external_id,
            "gtins": [{"gtin": "3830000000000"}],
        },
    }


def test_scraper_session_retries_and_request_validation():
    retry = build_session().get_adapter("https://").max_retries
    assert retry.total == 4
    assert 429 in retry.status_forcelist

    session = FakeSession([FakeResponse({"products": []})])
    payload = dobi_izdelke_kategorija("food", limit=20, offset=0, session=session)
    assert payload == {"products": []}
    assert session.calls[0][1]["timeout"] == DEFAULT_TIMEOUT

    with pytest.raises(ScraperError, match="request failed"):
        dobi_izdelke_kategorija("food", session=FakeSession([FakeResponse(status=500)]))
    with pytest.raises(ScraperError, match="products shape"):
        dobi_izdelke_kategorija("food", session=FakeSession([FakeResponse({"wrong": []})]))


def test_scraper_pagination_decimal_and_host_restriction():
    session = FakeSession(
        [
            FakeResponse({"products": [raw_product("1", total=2)]}),
            FakeResponse({"products": [raw_product("2", total=2)]}),
        ]
    )
    products = dobi_vse_izdelke_kategorija("food", limit=1, session=session, pause_seconds=0)
    assert [product["mercator_id"] for product in products] == ["1", "2"]
    assert products[0]["cena"] == Decimal("1.23")
    assert session.calls[1][1]["params"]["offset"] == 1
    with pytest.raises(ScraperError, match="untrusted"):
        pretvori_izdelek(raw_product("3", url="https://evil.example/product"))
    with pytest.raises(ScraperError, match="total changed"):
        dobi_vse_izdelke_kategorija(
            "food",
            limit=1,
            session=FakeSession(
                [
                    FakeResponse({"products": [raw_product("1", total=2)]}),
                    FakeResponse({"products": [raw_product("2", total=3)]}),
                ]
            ),
            pause_seconds=0,
        )


def test_persistence_requires_explicit_mapping(db):
    product_payload = {
        "mercator_id": "external-1",
        "ime": "Retail name",
        "cena": Decimal("4.25"),
        "gtin": "3830000000000",
        "url": "https://mercatoronline.si/product",
    }
    assert persist_catalog(db, [product_payload], date(2026, 1, 2)) == (1, 0)
    db.commit()
    assert db.scalar(select(func.count()).select_from(Cena)) == 0

    canonical = Izdelek(ime="Canonical", kategorija=None, enota="piece")
    db.add(canonical)
    db.flush()
    mapping = db.scalar(select(RetailerProduct).where(RetailerProduct.external_id == "external-1"))
    mapping.izdelek_id = canonical.id
    db.commit()

    assert persist_catalog(db, [product_payload], date(2026, 1, 2)) == (1, 1)
    db.commit()
    price = db.scalar(select(Cena))
    assert price.cena == Decimal("4.25")
    assert db.scalar(select(func.count()).select_from(Trgovina)) == 1
