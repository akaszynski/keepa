"""Shared utilities module for ``keepa``."""

import asyncio
import datetime
from typing import Any

import numpy as np
import pandas as pd

from keepa.constants import _SELLER_TIME_DATA_KEYS, DCODES, KEEPA_ST_ORDINAL, csv_indices
from keepa.models.domain import Domain


def is_documented_by(original):
    """Avoid copying the documentation."""

    def wrapper(target):
        target.__doc__ = original.__doc__
        return target

    return wrapper


def _normalize_value(v: int, isfloat: bool, key: str) -> float | None:
    """Normalize a single value based on its type and key context."""
    if v < 0:
        return None
    if isfloat:
        v = float(v) / 100
        if key == "RATING":
            v *= 10
    return v


def _is_stat_value_skippable(key: str, value: Any) -> bool:
    """Determine if the stat value is skippable."""
    if key in {
        "buyBoxSellerId",
        "sellerIdsLowestFBA",
        "sellerIdsLowestFBM",
        "buyBoxShippingCountry",
        "buyBoxAvailabilityMessage",
    }:
        return True

    # -1 or -2 --> not exist
    if isinstance(value, int) and value < 0:
        return True

    return False


def _parse_stat_value_list(
    value_list: list, to_datetime: bool
) -> dict[str, float | tuple[Any, float]]:
    """Parse a list of stat values into a structured dict."""
    convert_time = any(isinstance(v, list) for v in value_list if v is not None)
    result = {}

    for ind, key, isfloat in csv_indices:
        item = value_list[ind] if ind < len(value_list) else None
        if item is None:
            continue

        if convert_time:
            ts, val = item
            val = _normalize_value(val, isfloat, key)
            if val is not None:
                ts = keepa_minutes_to_time([ts], to_datetime)[0]
                result[key] = (ts, val)
        else:
            val = _normalize_value(item, isfloat, key)
            if val is not None:
                result[key] = val

    return result


def _parse_stats(stats: dict[str, None, int, list[int]], to_datetime: bool):
    """Parse numeric stats object.

    There is no need to parse strings or list of strings. Keepa stats object
    response documentation:
    https://keepa.com/#!discuss/t/statistics-object/1308
    """
    stats_parsed = {}

    for stat_key, stat_value in stats.items():
        if _is_stat_value_skippable(stat_key, stat_value):
            continue

        if stat_value is not None:
            if stat_key == "lastOffersUpdate":
                stats_parsed[stat_key] = keepa_minutes_to_time([stat_value], to_datetime)[0]
            elif isinstance(stat_value, list) and len(stat_value) > 0:
                stat_value_dict = _parse_stat_value_list(stat_value, to_datetime)
                if stat_value_dict:
                    stats_parsed[stat_key] = stat_value_dict
            else:
                stats_parsed[stat_key] = stat_value

    return stats_parsed


def _parse_seller(seller_raw_response, to_datetime):
    sellers = list(seller_raw_response.values())
    for seller in sellers:

        def convert_time_data(key):
            date_val = seller.get(key, None)
            if date_val is not None:
                return (key, keepa_minutes_to_time([date_val], to_datetime)[0])
            else:
                return None

        seller.update(
            filter(lambda p: p is not None, map(convert_time_data, _SELLER_TIME_DATA_KEYS))
        )

    return dict(map(lambda seller: (seller["sellerId"], seller), sellers))


def parse_csv(csv, to_datetime: bool = True, out_of_stock_as_nan: bool = True) -> dict[str, Any]:
    """
    Parse csv list from keepa into a python dictionary.

    Parameters
    ----------
    csv : list
        csv list from keepa
    to_datetime : bool, default: True
        Modifies numpy minutes to datetime.datetime values.
        Default True.
    out_of_stock_as_nan : bool, optional
        When True, prices are NAN when price category is out of stock.
        When False, prices are -0.01
        Default True

    Returns
    -------
    product_data : dict
        Dictionary containing the following fields with timestamps:

        AMAZON: Amazon price history

        NEW: Marketplace/3rd party New price history - Amazon is
            considered to be part of the marketplace as well, so if
            Amazon has the overall lowest new (!) price, the
            marketplace new price in the corresponding time interval
            will be identical to the Amazon price (except if there is
            only one marketplace offer).  Shipping and Handling costs
            not included!

        USED: Marketplace/3rd party Used price history

        SALES: Sales Rank history. Not every product has a Sales Rank.

        LISTPRICE: List Price history

        5 COLLECTIBLE: Collectible Price history

        6 REFURBISHED: Refurbished Price history

        7 NEW_FBM_SHIPPING: 3rd party (not including Amazon) New price
            history including shipping costs, only fulfilled by
            merchant (FBM).

        8 LIGHTNING_DEAL:  3rd party (not including Amazon) New price
            history including shipping costs, only fulfilled by
            merchant (FBM).

        9 WAREHOUSE: Amazon Warehouse Deals price history. Mostly of
            used condition, rarely new.

        10 NEW_FBA: Price history of the lowest 3rd party (not
             including Amazon/Warehouse) New offer that is fulfilled
             by Amazon

        11 COUNT_NEW: New offer count history

        12 COUNT_USED: Used offer count history

        13 COUNT_REFURBISHED: Refurbished offer count history

        14 COUNT_COLLECTIBLE: Collectible offer count history

        16 RATING: The product's rating history. A rating is an
             integer from 0 to 50 (e.g. 45 = 4.5 stars)

        17 COUNT_REVIEWS: The product's review count history.

        18 BUY_BOX_SHIPPING: The price history of the buy box. If no
            offer qualified for the buy box the price has the value
            -1. Including shipping costs.  The ``buybox`` parameter
            must be True for this field to be in the data.

        19 USED_NEW_SHIPPING: "Used - Like New" price history
            including shipping costs.

        20 USED_VERY_GOOD_SHIPPING: "Used - Very Good" price history
            including shipping costs.

        21 USED_GOOD_SHIPPING: "Used - Good" price history including
            shipping costs.

        22 USED_ACCEPTABLE_SHIPPING: "Used - Acceptable" price history
            including shipping costs.

        23 COLLECTIBLE_NEW_SHIPPING: "Collectible - Like New" price
            history including shipping costs.

        24 COLLECTIBLE_VERY_GOOD_SHIPPING: "Collectible - Very Good"
            price history including shipping costs.

        25 COLLECTIBLE_GOOD_SHIPPING: "Collectible - Good" price
            history including shipping costs.

        26 COLLECTIBLE_ACCEPTABLE_SHIPPING: "Collectible - Acceptable"
            price history including shipping costs.

        27 REFURBISHED_SHIPPING: Refurbished price history including
            shipping costs.

        30 TRADE_IN: The trade in price history. Amazon trade-in is
            not available for every locale.

        31 RENT: Rental price history. Requires use of the rental
            and offers parameter. Amazon Rental is only available
            for Amazon US.

    Notes
    -----
    Negative prices

    """
    product_data = {}

    for ind, key, isfloat in csv_indices:
        if csv[ind]:  # Check if entry it exists
            if "SHIPPING" in key:  # shipping price is included
                # Data goes [time0, value0, shipping0, time1, value1,
                #            shipping1, ...]
                times = csv[ind][::3]
                values = np.array(csv[ind][1::3])
                values += np.array(csv[ind][2::3])
            else:
                # Data goes [time0, value0, time1, value1, ...]
                times = csv[ind][::2]
                values = np.array(csv[ind][1::2])

            # Convert to float price if applicable
            if isfloat:
                nan_mask = values < 0
                values = values.astype(float) / 100
                if out_of_stock_as_nan:
                    values[nan_mask] = np.nan

                if key == "RATING":
                    values *= 10

            timeval = keepa_minutes_to_time(times, to_datetime)

            product_data["%s_time" % key] = timeval
            product_data[key] = values

            # combine time and value into a data frame using time as index
            product_data[f"df_{key}"] = pd.DataFrame({"value": values}, index=timeval)

    return product_data


def format_items(items):
    """Check if the input items are valid and formats them."""
    if isinstance(items, list) or isinstance(items, np.ndarray):
        return np.unique(items)
    elif isinstance(items, str):
        return np.asarray([items])


def _domain_to_dcode(domain: str | Domain) -> int:
    """Convert a domain to a domain code."""
    if isinstance(domain, Domain):
        domain_str = domain.value
    else:
        domain_str = domain

    if domain_str not in DCODES:
        raise ValueError(f"Invalid domain code {domain}. Should be one of the following:\n{DCODES}")
    return DCODES.index(domain_str)


def convert_offer_history(csv, to_datetime=True):
    """Convert an offer history to human readable values.

    Parameters
    ----------
    csv : list
       Offer list csv obtained from ``['offerCSV']``

    to_datetime : bool, optional
        Modifies ``numpy`` minutes to ``datetime.datetime`` values.
        Default ``True``.

    Returns
    -------
    times : numpy.ndarray
        List of time values for an offer history.

    prices : numpy.ndarray
        Price (including shipping) of an offer for each time at an
        index of times.

    """
    # convert these values to numpy arrays
    times = csv[::3]
    values = np.array(csv[1::3])
    values += np.array(csv[2::3])  # add in shipping

    # convert to dollars and datetimes
    times = keepa_minutes_to_time(times, to_datetime)
    prices = values / 100.0
    return times, prices


def _str_to_bool(string: str) -> bool:
    if string:
        return bool(int(string))
    return False


def process_used_buybox(buybox_info: list[str]) -> pd.DataFrame:
    """
    Process used buybox information to create a Pandas DataFrame.

    Parameters
    ----------
    buybox_info : list of str
        A list containing information about used buybox in a specific order:
        [Keepa time minutes, seller id, condition, isFBA, ...]

    Returns
    -------
    pd.DataFrame
        A DataFrame containing four columns:
        - 'datetime': Datetime objects converted from Keepa time minutes.
        - 'user_id': String representing the seller ID.
        - 'condition': String representing the condition of the product.
        - 'isFBA': Boolean indicating whether the offer is Fulfilled by Amazon.

    Notes
    -----
    The `condition` is mapped from its code to a descriptive string.
    The `isFBA` field is converted to a boolean.

    Examples
    --------
    Load in product offers and convert the buy box data into a
    ``pandas.DataFrame``.

    >>> import keepa
    >>> key = "<REAL_KEEPA_KEY>"
    >>> api = keepa.Keepa(key)
    >>> response = api.query("B0088PUEPK", offers=20)
    >>> product = response[0]
    >>> buybox_info = product["buyBoxUsedHistory"]
    >>> df = keepa.process_used_buybox(buybox_info)
                   datetime         user_id         condition  isFBA
    0   2022-11-02 16:46:00  A1QUAC68EAM09F   Used - Like New   True
    1   2022-11-13 10:36:00  A18WXU4I7YR6UA  Used - Very Good  False
    2   2022-11-15 23:50:00   AYUGEV9WZ4X5O   Used - Like New  False
    3   2022-11-17 06:16:00  A18WXU4I7YR6UA  Used - Very Good  False
    4   2022-11-17 10:56:00   AYUGEV9WZ4X5O   Used - Like New  False
    ..                  ...             ...               ...    ...
    115 2023-10-23 10:00:00   AYUGEV9WZ4X5O   Used - Like New  False
    116 2023-10-25 21:14:00  A1U9HDFCZO1A84   Used - Like New  False
    117 2023-10-26 04:08:00   AYUGEV9WZ4X5O   Used - Like New  False
    118 2023-10-27 08:14:00  A1U9HDFCZO1A84   Used - Like New  False
    119 2023-10-27 12:34:00   AYUGEV9WZ4X5O   Used - Like New  False

    """
    datetime_arr = []
    user_id_arr = []
    condition_map = {
        "": "Unknown",
        "2": "Used - Like New",
        "3": "Used - Very Good",
        "4": "Used - Good",
        "5": "Used - Acceptable",
    }
    condition_arr = []
    isFBA_arr = []

    for i in range(0, len(buybox_info), 4):
        keepa_time = int(buybox_info[i])
        datetime_arr.append(keepa_minutes_to_time([keepa_time])[0])
        user_id_arr.append(buybox_info[i + 1])
        condition_arr.append(condition_map[buybox_info[i + 2]])
        isFBA_arr.append(_str_to_bool(buybox_info[i + 3]))

    df = pd.DataFrame(
        {
            "datetime": datetime_arr,
            "user_id": user_id_arr,
            "condition": condition_arr,
            "isFBA": isFBA_arr,
        }
    )

    return df


def keepa_minutes_to_time(minutes, to_datetime=True):
    """Accept an array or list of minutes and converts it to a numpy datetime array.

    Assumes that keepa time is from keepa minutes from ordinal.
    """
    # Convert to timedelta64 and shift
    dt = np.array(minutes, dtype="timedelta64[m]")
    dt = dt + KEEPA_ST_ORDINAL  # shift from ordinal

    # Convert to datetime if requested
    if to_datetime:
        return dt.astype(datetime.datetime)
    return dt


def run_and_get(coro):
    """Attempt to run an async request."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    task = loop.create_task(coro)
    loop.run_until_complete(task)
    return task.result()
