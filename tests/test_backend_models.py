"""Tests for optional Pydantic backend model responses."""

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

import keepa
from keepa import backend_models

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ready_api() -> keepa.Keepa:
    api = keepa.Keepa("x" * 64, check_key=False)
    api.tokens_left = 100
    api.status.refillRate = 100
    api.status.refillIn = 0
    return api


def test_query_extra_params_default_is_not_mutable() -> None:
    assert inspect.signature(keepa.Keepa.query).parameters["extra_params"].default is None


def test_backend_aliases_round_trip() -> None:
    image = backend_models.Image.model_validate({"l": "https://example.com/image.jpg"})

    assert image.l_ == "https://example.com/image.jpg"
    assert image.model_dump(exclude_none=True, by_alias=True) == {
        "l": "https://example.com/image.jpg"
    }


def test_generated_backend_api_docs_are_complete() -> None:
    reference = (PROJECT_ROOT / "docs/source/backend_model_reference.rst").read_text()

    for export_name in backend_models.__all__:
        assert f"keepa.models.backend.{export_name}" in reference


@pytest.mark.parametrize(
    ("client", "reference_name"),
    [(keepa.Keepa, "sync_client.rst"), (keepa.AsyncKeepa, "async_client.rst")],
)
def test_public_client_api_docs_are_complete(client: type, reference_name: str) -> None:
    reference = (PROJECT_ROOT / "docs/source" / reference_name).read_text()
    public_members = {
        name
        for name, member in inspect.getmembers(client)
        if not name.startswith("_")
        and (inspect.isfunction(member) or inspect.ismethod(member) or isinstance(member, property))
    }

    for member_name in public_members:
        assert f"{client.__name__}.{member_name}" in reference


def test_query_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert request_type == "product"
        return {
            "products": [
                {
                    "asin": "B000000000",
                    "domainId": 1,
                    "csv": None,
                    "unknownFutureField": "kept",
                }
            ]
        }

    monkeypatch.setattr(api, "_request", fake_request)

    products = api.query("B000000000", history=False, progress_bar=False, typed=True)

    assert isinstance(products[0], backend_models.Product)
    assert products[0].asin == "B000000000"
    assert products[0].unknownFutureField == "kept"


def test_query_default_response_remains_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"products": [{"asin": "B000000000", "domainId": 1, "csv": None}]}

    monkeypatch.setattr(api, "_request", fake_request)

    products = api.query("B000000000", history=False, progress_bar=False)

    assert isinstance(products[0], dict)


def test_raw_query_cannot_be_typed() -> None:
    api = _ready_api()

    with pytest.raises(ValueError, match="typed=True"):
        api.query("B000000000", raw=True, typed=True, progress_bar=False)


def test_category_lookup_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"categories": {"1": {"catId": 1, "name": "Root"}}}

    monkeypatch.setattr(api, "_request", fake_request)

    categories = api.category_lookup(0, typed=True)

    assert isinstance(categories["1"], backend_models.Category)
    assert categories["1"].name == "Root"


def test_category_search_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"categories": {"1": {"catId": 1, "name": "Root"}}}

    monkeypatch.setattr(api, "_request", fake_request)

    categories = api.search_for_categories("root", typed=True)

    assert isinstance(categories["1"], backend_models.Category)


def test_seller_query_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {
            "sellers": {
                "A2L77EE7U53NWQ": {
                    "sellerId": "A2L77EE7U53NWQ",
                    "sellerName": "Amazon Warehouse",
                    "trackedSince": 1,
                }
            }
        }

    monkeypatch.setattr(api, "_request", fake_request)

    sellers = api.seller_query("A2L77EE7U53NWQ", typed=True)

    assert isinstance(sellers["A2L77EE7U53NWQ"], backend_models.Seller)
    assert sellers["A2L77EE7U53NWQ"].trackedSince == 1


def test_deals_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"deals": {"dr": [{"asin": "B000000000"}], "categoryIds": [1]}}

    monkeypatch.setattr(api, "_request", fake_request)

    deals = api.deals({"page": 0, "domainId": 1}, typed=True)

    assert isinstance(deals, backend_models.DealResponse)
    assert isinstance(deals.dr[0], backend_models.Deal)
    assert deals.dr[0].asin == "B000000000"


def test_deals_accepts_generated_request_model(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        selection = json.loads(payload["selection"])
        assert selection["page"] == 0
        assert selection["includeCategories"] == [123]
        return {"deals": {"dr": [{"asin": "B000000000"}]}}

    monkeypatch.setattr(api, "_request", fake_request)

    deals = api.deals(backend_models.DealRequest(page=0, includeCategories=[123]))

    assert deals["dr"][0]["asin"] == "B000000000"


def test_product_finder_accepts_generated_request_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        selection = json.loads(payload["selection"])
        assert selection["author"] == ["jim butcher"]
        assert selection["perPage"] == 50
        return {"asinList": ["B000HRMAR2"]}

    monkeypatch.setattr(api, "_request", fake_request)

    asins = api.product_finder(backend_models.ProductFinderRequest(author=["jim butcher"]))

    assert asins == ["B000HRMAR2"]


def test_product_finder_preserves_backend_filter_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert request_type == "query"
        selection = json.loads(payload["selection"])
        assert selection["sort"] == [["current_SALES", "desc"]]
        assert selection["buyBoxSellerId"] == ["A2L77EE7U53NWQ", "ATVPDKIKX0DER"]
        assert selection["partNumber"] == ["MX-1000", "MX-1001"]
        assert selection["categories_include"] == ["2619533011"]
        assert selection["perPage"] == 75
        return {"asinList": ["B000HRMAR2"]}

    monkeypatch.setattr(api, "_request", fake_request)

    asins = api.product_finder(
        {
            "sort": [["current_SALES", "desc"]],
            "buyBoxSellerId": ["A2L77EE7U53NWQ", "ATVPDKIKX0DER"],
            "partNumber": ["MX-1000", "MX-1001"],
            "categories_include": ["2619533011"],
            "perPage": 75,
        }
    )

    assert asins == ["B000HRMAR2"]


def test_best_sellers_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        assert request_type == "bestsellers"
        return {
            "bestSellersList": {
                "domainId": 1,
                "categoryId": 123,
                "asinList": ["B000000000"],
            }
        }

    monkeypatch.setattr(api, "_request", fake_request)

    best_sellers = api.best_sellers_query("123", typed=True)

    assert isinstance(best_sellers, backend_models.BestSellers)
    assert best_sellers.categoryId == 123
    assert best_sellers.asinList == ["B000000000"]


def test_best_sellers_default_response_remains_asin_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _ready_api()

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"bestSellersList": {"asinList": ["B000000000"]}}

    monkeypatch.setattr(api, "_request", fake_request)

    assert api.best_sellers_query("123") == ["B000000000"]


@pytest.mark.asyncio
async def test_async_query_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)
    api.tokens_left = 100
    api.status.refillRate = 100
    api.status.refillIn = 0

    async def fake_product_query(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"products": [{"asin": "B000000000", "domainId": 1, "csv": None}]}

    monkeypatch.setattr(api, "_product_query", fake_product_query)

    products = await api.query("B000000000", history=False, progress_bar=False, typed=True)

    assert isinstance(products[0], backend_models.Product)
    assert products[0].asin == "B000000000"


@pytest.mark.asyncio
async def test_async_category_endpoints_typed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)

    async def fake_request(
        request_type: str, payload: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if request_type == "category":
            assert payload["parents"] == 0
        return {"categories": {"1": {"catId": 1, "name": "Root"}}}

    monkeypatch.setattr(api, "_request", fake_request)

    search = await api.search_for_categories("root", typed=True)
    lookup = await api.category_lookup(0, typed=True)

    assert isinstance(search["1"], backend_models.Category)
    assert isinstance(lookup["1"], backend_models.Category)


@pytest.mark.asyncio
async def test_async_seller_query_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"sellers": {"SELLER": {"sellerId": "SELLER", "trackedSince": 1}}}

    monkeypatch.setattr(api, "_request", fake_request)

    sellers = await api.seller_query("SELLER", typed=True)

    assert isinstance(sellers["SELLER"], backend_models.Seller)


@pytest.mark.asyncio
async def test_async_deals_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"deals": {"dr": [{"asin": "B000000000"}]}}

    monkeypatch.setattr(api, "_request", fake_request)

    deals = await api.deals({"page": 0, "domainId": 1}, typed=True)

    assert isinstance(deals, backend_models.DealResponse)
    assert isinstance(deals.dr[0], backend_models.Deal)


@pytest.mark.asyncio
async def test_async_deals_accepts_generated_request_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = args[1]
        selection = json.loads(payload["selection"])
        assert selection["page"] == 0
        assert selection["includeCategories"] == [123]
        return {"deals": {"dr": [{"asin": "B000000000"}]}}

    monkeypatch.setattr(api, "_request", fake_request)

    deals = await api.deals(backend_models.DealRequest(page=0, includeCategories=[123]))

    assert deals["dr"][0]["asin"] == "B000000000"


@pytest.mark.asyncio
async def test_async_product_finder_accepts_generated_request_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = args[1]
        selection = json.loads(payload["selection"])
        assert selection["author"] == ["jim butcher"]
        assert selection["perPage"] == 50
        return {"asinList": ["B000HRMAR2"]}

    monkeypatch.setattr(api, "_request", fake_request)

    asins = await api.product_finder(backend_models.ProductFinderRequest(author=["jim butcher"]))

    assert asins == ["B000HRMAR2"]


@pytest.mark.asyncio
async def test_async_best_sellers_typed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    api = await keepa.AsyncKeepa.create("x" * 64)

    async def fake_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"bestSellersList": {"categoryId": 123, "asinList": ["B000000000"]}}

    monkeypatch.setattr(api, "_request", fake_request)

    best_sellers = await api.best_sellers_query("123", typed=True)

    assert isinstance(best_sellers, backend_models.BestSellers)
    assert best_sellers.asinList == ["B000000000"]
