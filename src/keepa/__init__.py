"""Keepa module."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("keepa")
except PackageNotFoundError:
    __version__ = "unknown"

from keepa.data_models import ProductParams
from keepa.interface import (
    DCODES,
    KEEPA_ST_ORDINAL,
    SCODES,
    AsyncKeepa,
    Domain,
    Keepa,
    convert_offer_history,
    csv_indices,
    format_items,
    keepa_minutes_to_time,
    parse_csv,
    process_used_buybox,
    run_and_get,
)
from keepa.plotting import plot_product

__all__ = [
    "ProductParams",
    "Domain",
    "DCODES",
    "KEEPA_ST_ORDINAL",
    "SCODES",
    "AsyncKeepa",
    "Keepa",
    "convert_offer_history",
    "csv_indices",
    "format_items",
    "keepa_minutes_to_time",
    "parse_csv",
    "process_used_buybox",
    "run_and_get",
    "plot_product",
    "__version__",
]
