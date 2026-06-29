"""Offline checks for structures mirrored from Keepa's backend API."""

import json
import math
from typing import Any

import pytest

import keepa
from keepa.constants import csv_indices
from keepa.query_keys import DEAL_REQUEST_KEYS
from keepa.utils import _parse_stats, parse_csv


def test_deal_request_keys_include_latest_backend_fields() -> None:
    latest_fields = {
        "isLowest90",
        "isBackInStock",
        "material",
        "type",
        "manufacturer",
        "brand",
        "productGroup",
        "model",
        "color",
        "size",
        "unitType",
        "scent",
        "itemForm",
        "pattern",
        "style",
        "itemTypeKeyword",
        "targetAudienceKeyword",
        "edition",
        "format",
        "author",
        "binding",
        "languages",
        "brandStoreName",
        "brandStoreUrlName",
        "websiteDisplayGroup",
        "websiteDisplayGroupName",
        "salesRankDisplayGroup",
    }

    assert latest_fields.issubset(DEAL_REQUEST_KEYS)
    assert "hasAmazonOffer" not in DEAL_REQUEST_KEYS


def test_product_params_include_latest_backend_fields() -> None:
    params = keepa.ProductParams(
        activeIngredients=["ceramide"],
        availabilityAmazonMinDelayInDays_gte=2,
        buyBoxEligibleOfferCountsNewFBA_lte=[[1, 2]],
        buyBoxStatsTopSellerId365="A2L77EE7U53NWQ",
        hasAPlus=True,
        historicalSellerIds=["A2L77EE7U53NWQ"],
        websiteDisplayGroup="kitchen_display_on_website",
        srAvg211_lte=1000,
    )

    dumped = params.model_dump(exclude_none=True)
    assert dumped["activeIngredients"] == ["ceramide"]
    assert dumped["srAvg211_lte"] == 1000


def test_csv_indices_include_latest_backend_types() -> None:
    assert csv_indices[-4:] == [
        (32, "BUY_BOX_USED_SHIPPING", True),
        (33, "PRIME_EXCL", True),
        (34, "COUNT_NEW_FBA", False),
        (35, "COUNT_NEW_FBM", False),
    ]


def test_parse_csv_handles_latest_backend_types() -> None:
    csv = [[] for _ in range(36)]
    csv[31] = [0, 250]
    csv[32] = [0, 100, 25]
    csv[33] = [0, 499]
    csv[34] = [0, 3]
    csv[35] = [0, 4]

    parsed = parse_csv(csv)

    assert parsed["RENT"][0] == 2.5
    assert parsed["BUY_BOX_USED_SHIPPING"][0] == 1.25
    assert parsed["PRIME_EXCL"][0] == 4.99
    assert parsed["COUNT_NEW_FBA"][0] == 3
    assert parsed["COUNT_NEW_FBM"][0] == 4


def test_parse_stats_handles_latest_backend_types() -> None:
    values = [None] * 36
    values[32] = [0, 100]
    values[33] = [0, 499]
    values[34] = [0, 3]
    values[35] = [0, 4]

    parsed = _parse_stats({"current": values}, to_datetime=True)
    current = parsed["current"]

    assert current["BUY_BOX_USED_SHIPPING"][1] == 1.0
    assert math.isclose(current["PRIME_EXCL"][1], 4.99)
    assert current["COUNT_NEW_FBA"][1] == 3
    assert current["COUNT_NEW_FBM"][1] == 4


def test_product_params_reject_unknown_backend_fields() -> None:
    with pytest.raises(ValueError):
        keepa.ProductParams(doesNotExist=1)


def test_deals_accepts_latest_backend_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    api = keepa.Keepa("x" * 64, check_key=False)

    def fake_request(request_type: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured["request_type"] = request_type
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {"deals": {"dr": []}}

    monkeypatch.setattr(api, "_request", fake_request)

    deals = api.deals(
        {
            "page": 0,
            "domainId": 1,
            "isLowest90": True,
            "isBackInStock": True,
            "brand": ["Keepa"],
            "material": ["cotton"],
            "salesRankDisplayGroup": ["kitchen_display_on_website"],
        },
        wait=False,
    )

    selection = json.loads(captured["payload"]["selection"])
    assert deals == {"dr": []}
    assert captured["request_type"] == "deal"
    assert captured["kwargs"] == {"wait": False}
    assert selection["isLowest90"] is True
    assert selection["isBackInStock"] is True
    assert selection["brand"] == ["Keepa"]
    assert selection["salesRankDisplayGroup"] == ["kitchen_display_on_website"]
