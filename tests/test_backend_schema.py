"""Schema checks against a pinned Keepa backend commit."""

import ast
import dataclasses
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import requests

import keepa
import keepa.models.product_params
from keepa import backend_models
from keepa.constants import _SELLER_TIME_DATA_KEYS, DCODES, SCODES, csv_indices
from keepa.models.domain import Domain
from keepa.models.status import Status
from keepa.query_keys import DEAL_REQUEST_KEYS
from keepa.utils import _parse_stats, parse_csv

BACKEND_COMMIT = "6e524d13bc25bdbe49be24d59a4b28feb9f98e5d"
BACKEND_RAW_BASE = (
    "https://raw.githubusercontent.com/keepacom/api_backend"
    f"/{BACKEND_COMMIT}/src/main/java/com/keepa/api/backend"
)
BACKEND_CONTENTS_URL = (
    "https://api.github.com/repos/keepacom/api_backend/contents/"
    "src/main/java/com/keepa/api/backend/structs"
)
BACKEND_SOURCE_DIR_ENV = "KEEPA_BACKEND_SOURCE_DIR"

JAVA_TYPE_TO_PYTHON_TYPE = {
    "String": str,
    "Integer": int,
    "int": int,
    "long": int,
    "Byte": int,
    "Boolean": bool,
    "boolean": bool,
    "Double": float,
    "Float": float,
    "Long": int,
}

# Keepa's backend marks RATING as non-price, but this library intentionally
# scales it like a price-like value so users get star ratings instead of 0-50.
CSV_PRICE_FLAG_OVERRIDES = {"RATING": True}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _backend_model_generator() -> Any:
    module_path = PROJECT_ROOT / "utilities" / "generate-backend-models.py"
    spec = importlib.util.spec_from_file_location("keepa_backend_model_generator", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load backend model generator from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _backend_source(filename: str) -> str:
    local_file = _local_backend_file(filename)
    if local_file is not None:
        return local_file.read_text()

    try:
        response = requests.get(f"{BACKEND_RAW_BASE}/{filename}", timeout=20)
    except requests.RequestException as exc:
        pytest.skip(f"Could not fetch Keepa backend source {filename}: {exc}")

    if response.status_code != 200:
        pytest.skip(f"Could not fetch Keepa backend source {filename}: HTTP {response.status_code}")
    return response.text


def _backend_struct_files() -> list[str]:
    source_dir = os.environ.get(BACKEND_SOURCE_DIR_ENV)
    if source_dir is not None and _local_backend_checkout_matches_commit():
        return sorted(path.name for path in (Path(source_dir) / "structs").glob("*.java"))

    try:
        response = requests.get(
            BACKEND_CONTENTS_URL,
            params={"ref": BACKEND_COMMIT},
            timeout=20,
        )
    except requests.RequestException as exc:
        pytest.skip(f"Could not list Keepa backend structs: {exc}")

    if response.status_code != 200:
        pytest.skip(f"Could not list Keepa backend structs: HTTP {response.status_code}")
    return sorted(item["name"] for item in response.json() if item["name"].endswith(".java"))


def _local_backend_checkout_matches_commit() -> bool:
    source_dir = os.environ.get(BACKEND_SOURCE_DIR_ENV)
    if source_dir is None:
        return False

    try:
        repo_root = Path(source_dir).resolve()
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        repo_root = Path(result.stdout.strip())
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return result.stdout.strip() == BACKEND_COMMIT


def _local_backend_file(filename: str) -> Path | None:
    source_dir = os.environ.get(BACKEND_SOURCE_DIR_ENV)
    if source_dir is None:
        return None

    local_file = Path(source_dir) / filename
    if local_file.is_file() and _local_backend_checkout_matches_commit():
        return local_file
    return None


def _java_fields(java_source: str) -> dict[str, str]:
    fields = re.findall(
        r"public\s+([\w\[\]<>, ]+)\s+(\w+)(?:\s*=\s*[^;]+)?\s*;",
        java_source,
    )
    return {name: java_type.strip() for java_type, name in fields}


def _java_declarations(java_source: str) -> dict[str, tuple[str, str]]:
    java_source = _strip_java_comments(java_source)
    declarations = {}
    pattern = re.compile(r"public\s+(?:static\s+)?(?:final\s+)?(class|enum)\s+(\w+)")
    for match in pattern.finditer(java_source):
        brace_start = java_source.find("{", match.end())
        if brace_start < 0:
            continue
        brace_end = _matching_brace(java_source, brace_start)
        declarations[match.group(2)] = (
            match.group(1),
            java_source[brace_start + 1 : brace_end],
        )
    return declarations


def _strip_java_comments(java_source: str) -> str:
    java_source = re.sub(r"/\*.*?\*/", "", java_source, flags=re.S)
    return re.sub(r"//.*", "", java_source)


def _matching_brace(source: str, brace_start: int) -> int:
    depth = 0
    for index in range(brace_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("Could not find matching Java brace")


def _top_level_java_class_fields(class_body: str) -> set[str]:
    class_body = _remove_nested_java_declarations(class_body)
    return {
        match.group(2)
        for match in re.finditer(
            r"public\s+(?!(?:static|final|transient)\b)([\w\[\].<>, ?]+)\s+(\w+)"
            r"(?:\s*=\s*[^;]+)?\s*;",
            class_body,
        )
    }


def _remove_nested_java_declarations(class_body: str) -> str:
    pattern = re.compile(r"public\s+(?:static\s+)?(?:final\s+)?(?:class|enum)\s+\w+")
    output = []
    cursor = 0
    for match in pattern.finditer(class_body):
        brace_start = class_body.find("{", match.end())
        if brace_start < 0:
            continue
        brace_end = _matching_brace(class_body, brace_start)
        output.append(class_body[cursor : match.start()])
        cursor = brace_end + 1
    output.append(class_body[cursor:])
    return "".join(output)


def _java_enum_values(java_source: str, enum_name: str) -> list[str]:
    match = re.search(rf"public\s+enum\s+{enum_name}\s*\{{(.*?)\}}", java_source, re.S)
    if match is None:
        raise AssertionError(f"Could not find Java enum {enum_name}")
    values_text = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
    return [value.strip() for value in values_text.split(",") if value.strip()]


def _java_enum_values_from_body(enum_body: str) -> list[str]:
    constants_text = enum_body.split(";", 1)[0]
    values = []
    for item in _split_top_level(constants_text, ","):
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", item)
        if match is not None:
            values.append(match.group(1))
    return values


def _split_top_level(text: str, separator: str) -> list[str]:
    parts = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "(<[":
            depth += 1
        elif char in ")>]":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def _response_status_codes(java_source: str) -> dict[str, str]:
    cases = re.findall(
        r"case\s+(\d+):\s*response\.status\s*=\s*ResponseStatus\.([A-Z_]+);",
        java_source,
    )
    return {status_code: status_name for status_code, status_name in cases}


def _expected_request_key_type(java_type: str) -> type:
    if java_type.endswith("[]"):
        return list
    return JAVA_TYPE_TO_PYTHON_TYPE[java_type]


def _product_params_fields() -> set[str]:
    module_path = Path(keepa.models.product_params.__file__)
    module = ast.parse(module_path.read_text())
    class_node = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "ProductParams"
    )
    return {
        node.target.id
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def _csv_types(java_source: str) -> list[tuple[int, str, bool]]:
    enum_body = java_source[
        java_source.index("public enum CsvType") : java_source.index("public enum AvailabilityType")
    ]
    matches = re.findall(
        r"\n\s*([A-Z0-9_]+)\((\d+),\s*(true|false),",
        enum_body,
    )
    return [
        (int(index), name, CSV_PRICE_FLAG_OVERRIDES.get(name, is_price == "true"))
        for name, index, is_price in matches
    ]


def _seller_scalar_keepa_time_fields(java_source: str) -> list[str]:
    top_level_source = java_source.split("public enum MerchantCsvType", 1)[0]
    fields = []
    for match in re.finditer(
        r"/\*\*((?:(?!\*/).)*)\*/\s*public\s+int\s+(\w+)\s*;",
        top_level_source,
        re.S,
    ):
        comment, name = match.groups()
        if "Keepa Time minutes" in comment:
            fields.append(name)
    return fields


def test_domain_codes_match_backend_commit() -> None:
    backend_locales = _java_enum_values(
        _backend_source("structs/AmazonLocale.java"), "AmazonLocale"
    )

    assert DCODES == backend_locales
    assert [domain.value for domain in Domain] == backend_locales


def test_status_codes_match_backend_commit() -> None:
    backend_status_codes = _response_status_codes(_backend_source("KeepaAPI.java"))

    assert SCODES == backend_status_codes


def test_response_status_model_enum_matches_backend_commit() -> None:
    backend_statuses = _java_enum_values(_backend_source("KeepaAPI.java"), "ResponseStatus")

    assert [status.value for status in backend_models.ResponseStatus] == backend_statuses


def test_backend_models_are_generated_from_pinned_backend_commit() -> None:
    assert backend_models.BACKEND_COMMIT == BACKEND_COMMIT


def test_backend_model_exports_are_public_and_complete() -> None:
    declarations = {}
    for file_name in _backend_struct_files():
        declarations.update(_java_declarations(_backend_source(f"structs/{file_name}")))

    expected_exports = {
        "BACKEND_COMMIT",
        "KeepaBackendModel",
        "ResponseStatus",
        *declarations,
    }

    assert set(backend_models.__all__) == expected_exports


def test_status_model_fields_match_backend_response_token_fields() -> None:
    backend_fields = _java_fields(_backend_source("structs/Response.java"))
    token_status_fields = {"tokensLeft", "refillIn", "refillRate", "timestamp"}

    assert token_status_fields.issubset(backend_fields)
    assert {field.name for field in dataclasses.fields(Status)} == token_status_fields


def test_seller_time_fields_match_backend_commit() -> None:
    backend_time_fields = _seller_scalar_keepa_time_fields(_backend_source("structs/Seller.java"))

    assert _SELLER_TIME_DATA_KEYS == backend_time_fields


def test_deal_request_keys_match_backend_commit() -> None:
    backend_fields = _java_fields(_backend_source("structs/DealRequest.java"))
    expected = {
        name: _expected_request_key_type(java_type) for name, java_type in backend_fields.items()
    }

    assert DEAL_REQUEST_KEYS == expected


def test_product_params_fields_match_backend_commit() -> None:
    backend_fields = set(_java_fields(_backend_source("structs/ProductFinderRequest.java")))

    assert _product_params_fields() == backend_fields


def test_csv_indices_match_backend_commit() -> None:
    backend_csv_types = _csv_types(_backend_source("structs/Product.java"))

    assert csv_indices == backend_csv_types


def test_backend_models_cover_all_generated_struct_declarations() -> None:
    declarations = {}
    for file_name in _backend_struct_files():
        declarations.update(_java_declarations(_backend_source(f"structs/{file_name}")))

    for name, (kind, body) in declarations.items():
        model_or_enum = getattr(backend_models, name)
        if kind == "enum":
            assert [member.value for member in model_or_enum] == _java_enum_values_from_body(body)
            continue

        backend_field_names = _top_level_java_class_fields(body)
        model_field_names = {
            field.alias or field_name for field_name, field in model_or_enum.model_fields.items()
        }
        assert model_field_names == backend_field_names


def test_backend_model_fields_have_specific_types() -> None:
    for export_name in backend_models.__all__:
        model = getattr(backend_models, export_name)
        if not isinstance(model, type) or not issubclass(model, backend_models.KeepaBackendModel):
            continue
        for field in model.model_fields.values():
            assert field.annotation is not Any, f"{model.__name__}.{field.alias} is untyped"
            assert "typing.Any" not in str(field.annotation), (
                f"{model.__name__}.{field.alias} contains an untyped value"
            )


def test_backend_model_field_descriptions_match_backend_javadocs() -> None:
    generator = _backend_model_generator()
    sources = {
        file_name: _backend_source(f"structs/{file_name}") for file_name in _backend_struct_files()
    }
    documented_fields = 0

    for declaration in generator._collect_declarations(sources):
        if declaration.kind != "class":
            continue

        model = getattr(backend_models, declaration.name)
        for field in generator._class_fields(declaration.body):
            if field.description is None:
                continue

            documented_fields += 1
            model_field = model.model_fields[generator._python_field_name(field.name)]
            assert model_field.description == field.description, (
                f"{declaration.name}.{field.name} description does not match backend Javadoc"
            )

    assert documented_fields >= 400


def test_backend_model_field_descriptions_are_cleaned_for_users() -> None:
    assert backend_models.Product.model_fields["asin"].description == "The ASIN of the product"
    assert (
        backend_models.Deal.model_fields["deltaPercent"].description
        == "Same as delta, but given in percent instead of absolute values.\n\n"
        "First dimension uses Product.CsvType, second dimension DealInterval"
    )
    assert (
        backend_models.Seller.model_fields["csv"].description
        == "Two dimensional history array that contains history data for this seller. First "
        "dimension index:\n\nMerchantCsvType\n\n0 - RATING: The merchant's rating in percent, "
        "Integer from 0 to 100.\n1 - RATING_COUNT: The merchant's total rating count, Integer."
    )


def test_product_params_accept_backend_fields_and_reject_unknown_fields() -> None:
    params = keepa.ProductParams(
        activeIngredients=["ceramide"],
        availabilityAmazonMinDelayInDays_gte=2,
        buyBoxEligibleOfferCountsNewFBA_lte=[[1, 2]],
        buyBoxStatsTopSellerId365="A2L77EE7U53NWQ",
        buyBoxSellerId=["A2L77EE7U53NWQ", "ATVPDKIKX0DER"],
        categories_include=["2619533011"],
        hasAPlus=True,
        historicalSellerIds=["A2L77EE7U53NWQ"],
        partNumber=["MX-1000", "MX-1001"],
        sort=[["current_SALES", "desc"]],
        websiteDisplayGroup="kitchen_display_on_website",
        srAvg211_lte=1000,
    )

    dumped = params.model_dump(exclude_none=True)
    assert dumped["activeIngredients"] == ["ceramide"]
    assert dumped["buyBoxSellerId"] == ["A2L77EE7U53NWQ", "ATVPDKIKX0DER"]
    assert dumped["categories_include"] == ["2619533011"]
    assert dumped["partNumber"] == ["MX-1000", "MX-1001"]
    assert dumped["sort"] == [["current_SALES", "desc"]]
    assert dumped["srAvg211_lte"] == 1000

    with pytest.raises(ValueError):
        keepa.ProductParams(doesNotExist=1)


def test_parse_csv_handles_latest_backend_types() -> None:
    csv = [[] for _ in range(len(csv_indices))]
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
    values = [None] * len(csv_indices)
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
