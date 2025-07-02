"""Keepa module."""

from importlib.metadata import PackageNotFoundError, version

# single source versioning from the installed package (stored in pyproject.toml)
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
