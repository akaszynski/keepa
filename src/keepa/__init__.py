"""Keepa module."""

from importlib.metadata import PackageNotFoundError, version

# single source versioning from the installed package (stored in pyproject.toml)
try:
    __version__ = version("keepa")
except PackageNotFoundError:
    __version__ = "unknown"

from keepa.constants import DCODES, KEEPA_ST_ORDINAL, SCODES, csv_indices
from keepa.keepa_async import AsyncKeepa
from keepa.keepa_sync import Keepa
from keepa.models.domain import Domain
from keepa.models.product_params import ProductParams
from keepa.plotting import plot_product
from keepa.utils import (
    convert_offer_history,
    format_items,
    keepa_minutes_to_time,
    parse_csv,
    process_used_buybox,
    run_and_get,
)

__all__ = [
    "AsyncKeepa",
    "DCODES",
    "Domain",
    "KEEPA_ST_ORDINAL",
    "Keepa",
    "ProductParams",
    "SCODES",
    "__version__",
    "convert_offer_history",
    "csv_indices",
    "format_items",
    "keepa_minutes_to_time",
    "parse_csv",
    "plot_product",
    "process_used_buybox",
    "run_and_get",
]
