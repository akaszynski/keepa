"""Interface module to download Amazon product and history data from keepa.com."""

import asyncio
import datetime
import json
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import aiohttp
import numpy as np
import pandas as pd
import requests
from tqdm import tqdm

from keepa.data_models import ProductParams
from keepa.query_keys import DEAL_REQUEST_KEYS


def is_documented_by(original):
    """Avoid copying the documentation."""

    def wrapper(target):
        target.__doc__ = original.__doc__
        return target

    return wrapper


log = logging.getLogger(__name__)

# hardcoded ordinal time from
KEEPA_ST_ORDINAL = np.datetime64("2011-01-01")

# Request limit
REQUEST_LIMIT = 100

# Status code dictionary/key
SCODES = {
    "400": "REQUEST_REJECTED",
    "402": "PAYMENT_REQUIRED",
    "405": "METHOD_NOT_ALLOWED",
    "429": "NOT_ENOUGH_TOKEN",
}

# domain codes
# Valid values: [ 1: com | 2: co.uk | 3: de | 4: fr | 5:
#                 co.jp | 6: ca | 7: cn | 8: it | 9: es | 10: in | 11: com.mx | 12: com.br ]
DCODES = ["RESERVED", "US", "GB", "DE", "FR", "JP", "CA", "CN", "IT", "ES", "IN", "MX", "BR"]

# csv indices. used when parsing csv and stats fields.
# https://github.com/keepacom/api_backend
# see api_backend/src/main/java/com/keepa/api/backend/structs/Product.java
# [index in csv, key name, isfloat(is price or rating)]
csv_indices: List[Tuple[int, str, bool]] = [
    (0, "AMAZON", True),
    (1, "NEW", True),
    (2, "USED", True),
    (3, "SALES", False),
    (4, "LISTPRICE", True),
    (5, "COLLECTIBLE", True),
    (6, "REFURBISHED", True),
    (7, "NEW_FBM_SHIPPING", True),
    (8, "LIGHTNING_DEAL", True),
    (9, "WAREHOUSE", True),
    (10, "NEW_FBA", True),
    (11, "COUNT_NEW", False),
    (12, "COUNT_USED", False),
    (13, "COUNT_REFURBISHED", False),
    (14, "CollectableOffers", False),
    (15, "EXTRA_INFO_UPDATES", False),
    (16, "RATING", True),
    (17, "COUNT_REVIEWS", False),
    (18, "BUY_BOX_SHIPPING", True),
    (19, "USED_NEW_SHIPPING", True),
    (20, "USED_VERY_GOOD_SHIPPING", True),
    (21, "USED_GOOD_SHIPPING", True),
    (22, "USED_ACCEPTABLE_SHIPPING", True),
    (23, "COLLECTIBLE_NEW_SHIPPING", True),
    (24, "COLLECTIBLE_VERY_GOOD_SHIPPING", True),
    (25, "COLLECTIBLE_GOOD_SHIPPING", True),
    (26, "COLLECTIBLE_ACCEPTABLE_SHIPPING", True),
    (27, "REFURBISHED_SHIPPING", True),
    (28, "EBAY_NEW_SHIPPING", True),
    (29, "EBAY_USED_SHIPPING", True),
    (30, "TRADE_IN", True),
    (31, "RENT", False),
]


def _parse_stats(stats: Dict[str, Union[None, int, List[int]]], to_datetime: bool):
    """Parse numeric stats object.

    There is no need to parse strings or list of strings. Keepa stats object
    response documentation:
    https://keepa.com/#!discuss/t/statistics-object/1308
    """
    stats_keys_parse_not_required = {
        "buyBoxSellerId",
        "sellerIdsLowestFBA",
        "sellerIdsLowestFBM",
        "buyBoxShippingCountry",
        "buyBoxAvailabilityMessage",
    }
    stats_parsed = {}

    for stat_key, stat_value in stats.items():
        if stat_key in stats_keys_parse_not_required:
            stat_value = None

        elif (
            isinstance(stat_value, int) and stat_value < 0
        ):  # -1 or -2 means not exist. 0 doesn't mean not exist.
            stat_value = None

        if stat_value is not None:
            if stat_key == "lastOffersUpdate":
                stats_parsed[stat_key] = keepa_minutes_to_time([stat_value], to_datetime)[0]
            elif isinstance(stat_value, list) and len(stat_value) > 0:
                stat_value_dict = {}
                convert_time_in_value_pair = any(
                    map(lambda v: v is not None and isinstance(v, list), stat_value)
                )

                for ind, key, isfloat in csv_indices:
                    stat_value_item = stat_value[ind] if ind < len(stat_value) else None

                    def normalize_value(v):
                        if v < 0:
                            return None

                        if isfloat:
                            v = float(v) / 100
                            if key == "RATING":
                                v = v * 10

                        return v

                    if stat_value_item is not None:
                        if convert_time_in_value_pair:
                            stat_value_time, stat_value_item = stat_value_item
                            stat_value_item = normalize_value(stat_value_item)
                            if stat_value_item is not None:
                                stat_value_time = keepa_minutes_to_time(
                                    [stat_value_time], to_datetime
                                )[0]
                                stat_value_item = (stat_value_time, stat_value_item)
                        else:
                            stat_value_item = normalize_value(stat_value_item)

                    if stat_value_item is not None:
                        stat_value_dict[key] = stat_value_item

                if len(stat_value_dict) > 0:
                    stats_parsed[stat_key] = stat_value_dict
            else:
                stats_parsed[stat_key] = stat_value

    return stats_parsed


_seller_time_data_keys = ["trackedSince", "lastUpdate"]


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
            filter(lambda p: p is not None, map(convert_time_data, _seller_time_data_keys))
        )

    return dict(map(lambda seller: (seller["sellerId"], seller), sellers))


def parse_csv(csv, to_datetime=True, out_of_stock_as_nan=True):
    """Parse csv list from keepa into a python dictionary.

    Parameters
    ----------
    csv : list
        csv list from keepa

    to_datetime : bool, optional
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


class Domain(Enum):
    """Enumeration for Amazon domain regions.

    Examples
    --------
    >>> import keepa
    >>> keepa.Domain.US
    <Domain.US: 'US'>

    """

    RESERVED = "RESERVED"
    US = "US"
    GB = "GB"
    DE = "DE"
    FR = "FR"
    JP = "JP"
    CA = "CA"
    RESERVED2 = "RESERVED2"
    IT = "IT"
    ES = "ES"
    IN = "IN"
    MX = "MX"
    BR = "BR"


def _domain_to_dcode(domain: Union[str, Domain]) -> int:
    """Convert a domain to a domain code."""
    if isinstance(domain, Domain):
        domain_str = domain.value
    else:
        domain_str = domain

    if domain not in DCODES:
        raise ValueError(f"Invalid domain code {domain}. Should be one of the following:\n{DCODES}")
    return DCODES.index(domain_str)


class Keepa:
    r"""Support a synchronous Python interface to keepa server.

    Initializes API with access key.  Access key can be obtained by
    signing up for a reoccurring or one time plan at:
    https://keepa.com/#!api

    Parameters
    ----------
    accesskey : str
        64 character access key string.
    timeout : float, optional
        Default timeout when issuing any request.  This is not a time
        limit on the entire response download; rather, an exception is
        raised if the server has not issued a response for timeout
        seconds.  Setting this to 0 disables the timeout, but will
        cause any request to hang indefiantly should keepa.com be down
    logging_level: string, optional
        Logging level to use.  Default is 'DEBUG'.  Other options are
        'INFO', 'WARNING', 'ERROR', and 'CRITICAL'.

    Examples
    --------
    Create the api object.

    >>> import keepa
    >>> key = "<REAL_KEEPA_KEY>"
    >>> api = keepa.Keepa(key)

    Request data from two ASINs.

    >>> products = api.query(["0439064872", "1426208081"])

    Print item details.

    >>> print("Item 1")
    >>> print("\t ASIN: {:s}".format(products[0]["asin"]))
    >>> print("\t Title: {:s}".format(products[0]["title"]))
    Item 1
        ASIN: 0439064872
        Title: Harry Potter and the Chamber of Secrets (2)

    Print item price.

    >>> usedprice = products[0]["data"]["USED"]
    >>> usedtimes = products[0]["data"]["USED_time"]
    >>> print("\t Used price: ${:.2f}".format(usedprice[-1]))
    >>> print("\t as of: {:s}".format(str(usedtimes[-1])))
        Used price: $0.52
        as of: 2023-01-03 04:46:00

    """

    def __init__(self, accesskey: str, timeout: float = 10.0, logging_level: str = "DEBUG"):
        """Initialize server connection."""
        self.accesskey = accesskey
        self.tokens_left = 0
        self._timeout = timeout

        # Set up logging
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if logging_level not in levels:
            raise TypeError("logging_level must be one of: " + ", ".join(levels))
        log.setLevel(logging_level)
        # Store user's available tokens
        log.info("Connecting to keepa using key ending in %s", accesskey[-6:])
        self.status = self.update_status()
        log.info("%d tokens remain", self.tokens_left)

    @property
    def time_to_refill(self) -> float:
        """Return the time to refill in seconds.

        Examples
        --------
        Return the time to refill. If you have tokens available, this time
        should be 0.0 seconds.

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> api.time_to_refill
        0.0

        """
        # Get current timestamp in milliseconds from UNIX epoch
        now = int(time.time() * 1000)
        timeatrefile = self.status["timestamp"] + self.status["refillIn"]

        # wait plus one second fudge factor
        timetorefil = timeatrefile - now + 1000
        if timetorefil < 0:
            timetorefil = 0

        # Account for negative tokens left
        if self.tokens_left < 0:
            timetorefil += (abs(self.tokens_left) / self.status["refillRate"]) * 60000

        # Return value in seconds
        return timetorefil / 1000.0

    def update_status(self) -> Dict[str, Any]:
        """Update available tokens."""
        status = self._request("token", {"key": self.accesskey}, wait=False)
        self.status = status
        return status

    def wait_for_tokens(self) -> None:
        """Check if there are any remaining tokens and waits if none are available."""
        self.update_status()

        # Wait if no tokens available
        if self.tokens_left <= 0:
            tdelay = self.time_to_refill
            log.warning("Waiting %.0f seconds for additional tokens" % tdelay)
            time.sleep(tdelay)
            self.update_status()

    def query(
        self,
        items: Union[str, Sequence[str]],
        stats: Optional[Union[int]] = None,
        domain: str = "US",
        history: bool = True,
        offers: Optional[int] = None,
        update: Optional[int] = None,
        to_datetime: bool = True,
        rating: bool = False,
        out_of_stock_as_nan: bool = True,
        stock: bool = False,
        product_code_is_asin: bool = True,
        progress_bar: bool = True,
        buybox: bool = False,
        wait: bool = True,
        days: Optional[int] = None,
        only_live_offers: Optional[bool] = None,
        raw: bool = False,
    ) -> List[Dict[str, Any]]:
        """Perform a product query of a list, array, or single ASIN.

        Returns a list of product data with one entry for each
        product.

        Parameters
        ----------
        items : str, Sequence[str]
            A list, array, or single asin, UPC, EAN, or ISBN-13 identifying a
            product. ASINs should be 10 characters and match a product on
            Amazon. Items not matching Amazon product or duplicate Items will
            return no data. When using non-ASIN items, set
            ``product_code_is_asin`` to ``False``.

        stats : int or date, optional
            No extra token cost. If specified the product object will
            have a stats field with quick access to current prices,
            min/max prices and the weighted mean values. If the offers
            parameter was used it will also provide stock counts and
            buy box information.

            You can provide the stats parameter in two forms:

            Last x days (positive integer value): calculates the stats
            of the last x days, where x is the value of the stats
            parameter.  Interval: You can provide a date range for the
            stats calculation. You can specify the range via two
            timestamps (unix epoch time milliseconds) or two date
            strings (ISO8601, with or without time in UTC).

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        history : bool, optional
            When set to True includes the price, sales, and offer
            history of a product.  Set to False to reduce request time
            if data is not required.  Default True

        offers : int, optional
            Adds available offers to product data. Default 0. Must be between
            20 and 100. Enabling this also enables the ``"buyBoxUsedHistory"``.

        update : int, optional
            If data is older than the input integer, keepa will update their
            database and return live data. If set to 0 (live data), request may
            cost an additional token. Default (``None``) will not update.

        to_datetime : bool, default: True
            Modifies numpy minutes to datetime.datetime values.

        rating : bool, default: False
            When set to to True, includes the existing RATING and
            COUNT_REVIEWS history of the csv field.

        out_of_stock_as_nan : bool, default: True
            When True, prices are NAN when price category is out of
            stock.  When False, prices are -0.01.

        stock : bool, default: False
            Can only be used if the offers parameter is also True. If
            True, the stock will be collected for all retrieved live
            offers. Note: We can only determine stock up 10 qty. Stock
            retrieval takes additional time, expect the request to
            take longer. Existing stock history will be included
            whether or not the stock parameter is used.

        product_code_is_asin : bool, default: True
            The type of product code you are requesting. True when
            product code is an ASIN, an Amazon standard identification
            number, or 'code', for UPC, EAN, or ISBN-13 codes.

        progress_bar : bool, default: True
            Display a progress bar using ``tqdm``.

        buybox : bool, optional
            Additional token cost: 2 per product). When true the
            product and statistics object will include all available
            buy box related data:

            - current price, price history, and statistical values
            - buyBoxSellerIdHistory
            - all buy box fields in the statistics object

            The buybox parameter does not trigger a fresh data collection. If
            the offers parameter is used the buybox parameter is ignored, as
            the offers parameter also provides access to all buy box related
            data. To access the statistics object the stats parameter is
            required.

        wait : bool, default: True
            Wait available token before doing effective query.

        only_live_offers : bool, optional
            If set to True, the product object will only include live
            marketplace offers (when used in combination with the
            offers parameter). If you do not need historical offers
            use this to have them removed from the response. This can
            improve processing time and considerably decrease the size
            of the response.

        days : int, optional
            Any positive integer value. If specified and has positive value X
            the product object will limit all historical data to the recent X
            days.  This includes the csv, buyBoxSellerIdHistory, salesRanks,
            offers and offers.offerCSV fields. If you do not need old
            historical data use this to have it removed from the response. This
            can improve processing time and considerably decrease the size of
            the response.  The parameter does not use calendar days - so 1 day
            equals the last 24 hours.  The oldest data point of each field may
            have a date value which is out of the specified range. This means
            the value of the field has not changed since that date and is still
            active.

        raw : bool, default; False
            When ``True``, return the raw request response. This is
            only available in the non-async class.

        Returns
        -------
        list
            List of products when ``raw=False``.  Each product
            within the list is a dictionary.  The keys of each item
            may vary, so see the keys within each product for further
            details.

            Each product should contain at a minimum a "data" key
            containing a formatted dictionary.  For the available
            fields see the notes section

            When ``raw=True``, a list of unparsed responses are
            returned as :class:`requests.models.Response`.

            See: https://keepa.com/#!discuss/t/product-object/116

        Notes
        -----
        The following are some of the fields a product dictionary. For a full
        list and description, please see:
        `product-object <https://keepa.com/#!discuss/t/product-object/116>`_

        AMAZON
            Amazon price history

        NEW
            Marketplace/3rd party New price history - Amazon is
            considered to be part of the marketplace as well, so if
            Amazon has the overall lowest new (!) price, the
            marketplace new price in the corresponding time interval
            will be identical to the Amazon price (except if there is
            only one marketplace offer).  Shipping and Handling costs
            not included!

        USED
            Marketplace/3rd party Used price history

        SALES
            Sales Rank history. Not every product has a Sales Rank.

        LISTPRICE
            List Price history

        COLLECTIBLE
            Collectible Price history

        REFURBISHED
            Refurbished Price history

        NEW_FBM_SHIPPING
            3rd party (not including Amazon) New price history
            including shipping costs, only fulfilled by merchant
            (FBM).

        LIGHTNING_DEAL
            3rd party (not including Amazon) New price history
            including shipping costs, only fulfilled by merchant
            (FBM).

        WAREHOUSE
            Amazon Warehouse Deals price history. Mostly of used
            condition, rarely new.

        NEW_FBA
             Price history of the lowest 3rd party (not including
             Amazon/Warehouse) New offer that is fulfilled by Amazon

        COUNT_NEW
             New offer count history

        COUNT_USED
            Used offer count history

        COUNT_REFURBISHED
             Refurbished offer count history

        COUNT_COLLECTIBLE
             Collectible offer count history

        RATING
             The product's rating history. A rating is an integer from
             0 to 50 (e.g. 45 = 4.5 stars)

        COUNT_REVIEWS
            The product's review count history.

        BUY_BOX_SHIPPING
            The price history of the buy box. If no offer qualified
            for the buy box the price has the value -1. Including
            shipping costs.

        USED_NEW_SHIPPING
            "Used - Like New" price history including shipping costs.

        USED_VERY_GOOD_SHIPPING
            "Used - Very Good" price history including shipping costs.

        USED_GOOD_SHIPPING
            "Used - Good" price history including shipping costs.

        USED_ACCEPTABLE_SHIPPING
            "Used - Acceptable" price history including shipping costs.

        COLLECTIBLE_NEW_SHIPPING
            "Collectible - Like New" price history including shipping
            costs.

        COLLECTIBLE_VERY_GOOD_SHIPPING
            "Collectible - Very Good" price history including shipping
            costs.

        COLLECTIBLE_GOOD_SHIPPING
            "Collectible - Good" price history including shipping
            costs.

        COLLECTIBLE_ACCEPTABLE_SHIPPING
            "Collectible - Acceptable" price history including
            shipping costs.

        REFURBISHED_SHIPPING
            Refurbished price history including shipping costs.

        TRADE_IN
            The trade in price history. Amazon trade-in is not
            available for every locale.

        BUY_BOX_SHIPPING
            The price history of the buy box. If no offer qualified
            for the buy box the price has the value -1. Including
            shipping costs.  The ``buybox`` parameter must be True for
            this field to be in the data.

        Examples
        --------
        Query for product with ASIN ``'B0088PUEPK'`` using the synchronous
        keepa interface.

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> response = api.query("B0088PUEPK")
        >>> response[0]["title"]
        'Western Digital 1TB WD Blue PC Internal Hard Drive HDD - 7200 RPM,
        SATA 6 Gb/s, 64 MB Cache, 3.5" - WD10EZEX'

        Query for product with ASIN ``'B0088PUEPK'`` using the asynchronous
        keepa interface.

        >>> import asyncio
        >>> import keepa
        >>> async def main():
        ...     key = "<REAL_KEEPA_KEY>"
        ...     api = await keepa.AsyncKeepa().create(key)
        ...     return await api.query("B0088PUEPK")
        ...
        >>> response = asyncio.run(main())
        >>> response[0]["title"]
        'Western Digital 1TB WD Blue PC Internal Hard Drive HDD - 7200 RPM,
        SATA 6 Gb/s, 64 MB Cache, 3.5" - WD10EZEX'

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
        # Format items into numpy array
        try:
            items = format_items(items)
        except BaseException:
            raise ValueError("Invalid product codes input")
        if not len(items):
            raise ValueError("No valid product codes")

        nitems = len(items)
        if nitems == 1:
            log.debug("Executing single product query")
        else:
            log.debug("Executing %d item product query", nitems)

        # check offer input
        if offers:
            if not isinstance(offers, int):
                raise TypeError('Parameter "offers" must be an interger')

            if offers > 100 or offers < 20:
                raise ValueError('Parameter "offers" must be between 20 and 100')

        # Report time to completion
        tcomplete = (
            float(nitems - self.tokens_left) / self.status["refillRate"]
            - (60000 - self.status["refillIn"]) / 60000.0
        )
        if tcomplete < 0.0:
            tcomplete = 0.5
        log.debug(
            "Estimated time to complete %d request(s) is %.2f minutes",
            nitems,
            tcomplete,
        )
        log.debug("\twith a refill rate of %d token(s) per minute", self.status["refillRate"])

        # product list
        products = []

        pbar = None
        if progress_bar:
            pbar = tqdm(total=nitems)

        # Number of requests is dependent on the number of items and
        # request limit.  Use available tokens first
        idx = 0  # or number complete
        while idx < nitems:
            nrequest = nitems - idx

            # cap request
            if nrequest > REQUEST_LIMIT:
                nrequest = REQUEST_LIMIT

            # request from keepa and increment current position
            item_request = items[idx : idx + nrequest]  # noqa: E203
            response = self._product_query(
                item_request,
                product_code_is_asin,
                stats=stats,
                domain=domain,
                stock=stock,
                offers=offers,
                update=update,
                history=history,
                rating=rating,
                to_datetime=to_datetime,
                out_of_stock_as_nan=out_of_stock_as_nan,
                buybox=buybox,
                wait=wait,
                days=days,
                only_live_offers=only_live_offers,
                raw=raw,
            )
            idx += nrequest
            if raw:
                products.append(response)
            else:
                products.extend(response["products"])

            if pbar is not None:
                pbar.update(nrequest)

        return products

    def _product_query(self, items, product_code_is_asin=True, **kwargs):
        """Send query to keepa server and returns parsed JSON result.

        Parameters
        ----------
        items : np.ndarray
            Array of asins.  If UPC, EAN, or ISBN-13, as_asin must be
            False.  Must be between 1 and 100 ASINs

        as_asin : bool, optional
            Interpret product codes as ASINs only.

        stats : int or date format
            Set the stats time for get sales rank inside this range

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        offers : bool, optional
            Adds product offers to product data.

        update : int, optional
            If data is older than the input integer, keepa will update
            their database and return live data.  If set to 0 (live
            data), then request may cost an additional token.

        history : bool, optional
            When set to True includes the price, sales, and offer
            history of a product.  Set to False to reduce request time
            if data is not required.

        as_asin : bool, optional
            Queries keepa using asin codes.  Otherwise, queries using
            the code key.

        Returns
        -------
        products : list
            List of products.  Length equal to number of successful
            ASINs.

        refillIn : float
            Time in milliseconds to the next refill of tokens.

        refilRate : float
            Number of tokens refilled per minute

        timestamp : float

        tokensLeft : int
            Remaining tokens

        tz : int
            Timezone.  0 is UTC

        """
        # ASINs convert to comma joined string
        assert len(items) <= 100

        if product_code_is_asin:
            kwargs["asin"] = ",".join(items)
        else:
            kwargs["code"] = ",".join(items)

        kwargs["key"] = self.accesskey
        kwargs["domain"] = _domain_to_dcode(kwargs["domain"])

        # Convert bool values to 0 and 1.
        kwargs["stock"] = int(kwargs["stock"])
        kwargs["history"] = int(kwargs["history"])
        kwargs["rating"] = int(kwargs["rating"])
        kwargs["buybox"] = int(kwargs["buybox"])

        if kwargs["update"] is None:
            del kwargs["update"]
        else:
            kwargs["update"] = int(kwargs["update"])

        if kwargs["offers"] is None:
            del kwargs["offers"]
        else:
            kwargs["offers"] = int(kwargs["offers"])

        if kwargs["only_live_offers"] is None:
            del kwargs["only_live_offers"]
        else:
            # Keepa's param actually doesn't use snake_case.
            kwargs["only-live-offers"] = int(kwargs.pop("only_live_offers"))

        if kwargs["days"] is None:
            del kwargs["days"]
        else:
            assert kwargs["days"] > 0

        if kwargs["stats"] is None:
            del kwargs["stats"]

        out_of_stock_as_nan = kwargs.pop("out_of_stock_as_nan", True)
        to_datetime = kwargs.pop("to_datetime", True)

        # Query and replace csv with parsed data if history enabled
        wait = kwargs.get("wait")
        kwargs.pop("wait", None)
        raw_response = kwargs.pop("raw", False)
        response = self._request("product", kwargs, wait=wait, raw_response=raw_response)

        if kwargs["history"] and not raw_response:
            for product in response["products"]:
                if product["csv"]:  # if data exists
                    product["data"] = parse_csv(product["csv"], to_datetime, out_of_stock_as_nan)

        if kwargs.get("stats", None) and not raw_response:
            for product in response["products"]:
                stats = product.get("stats", None)
                if stats:
                    product["stats_parsed"] = _parse_stats(stats, to_datetime)

        return response

    def best_sellers_query(
        self, category, rank_avg_range=0, domain: Union[str, Domain] = "US", wait=True
    ):
        """Retrieve an ASIN list of the most popular products.

        This is based on sales in a specific category or product group.  See
        "search_for_categories" for information on how to get a category.

        Root category lists (e.g. "Home & Kitchen") or product group
        lists contain up to 100,000 ASINs.

        Sub-category lists (e.g. "Home Entertainment Furniture")
        contain up to 3,000 ASINs. As we only have access to the
        product's primary sales rank and not the ones of all
        categories it is listed in, the sub-category lists are created
        by us based on the product's primary sales rank and do not
        reflect the actual ordering on Amazon.

        Lists are ordered, starting with the best selling product.

        Lists are updated daily.  If a product does not have an
        accessible sales rank it will not be included in the
        lists. This in particular affects many products in the
        Clothing and Sports & Outdoors categories.

        We can not correctly identify the sales rank reference
        category in all cases, so some products may be misplaced.

        Parameters
        ----------
        category : str
            The category node id of the category you want to request
            the best sellers list for. You can find category node ids
            via the category search "search_for_categories".

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        wait : bool, optional
            Wait available token before doing effective query.
            Defaults to ``True``.

        Returns
        -------
        best_sellers : list
            List of best seller ASINs

        Examples
        --------
        Query for the best sellers among the ``"movies"`` category.

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> categories = api.search_for_categories("movies")
        >>> category = list(categories.items())[0][0]
        >>> asins = api.best_sellers_query(category)
        >>> asins
        ['B0BF3P5XZS',
         'B08JQN5VDT',
         'B09SP8JPPK',
         '0999296345',
         'B07HPG684T',
         '1984825577',
        ...

        Query for the best sellers among the ``"movies"`` category using the
        asynchronous keepa interface.

        >>> import asyncio
        >>> import keepa
        >>> async def main():
        ...     key = "<REAL_KEEPA_KEY>"
        ...     api = await keepa.AsyncKeepa().create(key)
        ...     categories = await api.search_for_categories("movies")
        ...     category = list(categories.items())[0][0]
        ...     return await api.best_sellers_query(category)
        ...
        >>> asins = asyncio.run(main())
        >>> asins
        ['B0BF3P5XZS',
         'B08JQN5VDT',
         'B09SP8JPPK',
         '0999296345',
         'B07HPG684T',
         '1984825577',
        ...

        """
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "category": category,
            "range": rank_avg_range,
        }

        response = self._request("bestsellers", payload, wait=wait)
        if "bestSellersList" in response:
            return response["bestSellersList"]["asinList"]
        else:  # pragma: no cover
            log.info("Best sellers search results not yet available")

    def search_for_categories(
        self, searchterm, domain: Union[str, Domain] = "US", wait=True
    ) -> list:
        """Search for categories from Amazon.

        Parameters
        ----------
        searchterm : str
            Input search term.

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        wait : bool, default: True
            Wait available token before doing effective query.
            Defaults to ``True``.

        Returns
        -------
        list
            The response contains a categories list with all matching
            categories.

        Examples
        --------
        Print all categories from science.

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> categories = api.search_for_categories("science")
        >>> for cat_id in categories:
        ...     print(cat_id, categories[cat_id]["name"])
        ...
        9091159011 Behavioral Sciences
        8407535011 Fantasy, Horror & Science Fiction
        8407519011 Sciences & Technology
        12805 Science & Religion
        13445 Astrophysics & Space Science
        12038 Science Fiction & Fantasy
        3207 Science, Nature & How It Works
        144 Science Fiction & Fantasy

        """
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "type": "category",
            "term": searchterm,
        }

        response = self._request("search", payload, wait=wait)
        if response["categories"] == {}:  # pragma no cover
            raise RuntimeError(
                "Categories search results not yet available " "or no search terms found."
            )
        return response["categories"]

    def category_lookup(
        self, category_id, domain: Union[str, Domain] = "US", include_parents=False, wait=True
    ):
        """Return root categories given a categoryId.

        Parameters
        ----------
        category_id : int
            ID for specific category or 0 to return a list of root
            categories.

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        include_parents : bool, default: False
            Include parents.

        wait : bool, default: True
            Wait available token before doing effective query.

        Returns
        -------
        list
            Output format is the same as search_for_categories.

        Examples
        --------
        Use 0 to return all root categories.

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> categories = api.category_lookup(0)

        Output the first category.

        >>> list(categories.values())[0]
        {'domainId': 1,
         'catId': 133140011,
         'name': 'Kindle Store',
         'children': [133141011,
          133143011,
          6766606011,
          7529231011,
          118656435011,
          2268072011,
          119757513011,
          358606011,
          3000677011,
          1293747011],
         'parent': 0,
         'highestRank': 6984155,
         'productCount': 6417325,
         'contextFreeName': 'Kindle Store',
         'lowestRank': 1,
         'matched': True}

        """
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "category": category_id,
            "parents": int(include_parents),
        }

        response = self._request("category", payload, wait=wait)
        if response["categories"] == {}:  # pragma no cover
            raise Exception("Category lookup results not yet available or no match found.")
        return response["categories"]

    def seller_query(
        self,
        seller_id,
        domain: Union[str, Domain] = "US",
        to_datetime=True,
        storefront=False,
        update=None,
        wait=True,
    ):
        """Receive seller information for a given seller id.

        If a seller is not found no tokens will be consumed.

        Token cost: 1 per requested seller

        Parameters
        ----------
        seller_id : str or list
            The seller id of the merchant you want to request. For
            batch requests, you may submit a list of 100 seller_ids.
            The seller id can also be found on Amazon on seller
            profile pages in the seller parameter of the URL as well
            as in the offers results from a product query.

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        storefront : bool, optional
            If specified the seller object will contain additional
            information about what items the seller is listing on Amazon.
            This includes a list of ASINs as well as the total amount of
            items the seller has listed. The following seller object
            fields will be set if data is available: asinList,
            asinListLastSeen, totalStorefrontAsinsCSV. If no data is
            available no additional tokens will be consumed. The ASIN
            list can contain up to 100,000 items. As using the storefront
            parameter does not trigger any new collection it does not
            increase the processing time of the request, though the
            response may be much bigger in size. The total storefront
            ASIN count will not be updated, only historical data will
            be provided (when available).

        update : int, optional
            Positive integer value. If the last live data collection from
            the Amazon storefront page is older than update hours force a
            new collection. Use this parameter in conjunction with the
            storefront parameter. Token cost will only be applied if a new
            collection is triggered.

            Using this parameter you can achieve the following:

            - Retrieve data from Amazon: a storefront ASIN list
              containing up to 2,400 ASINs, in addition to all ASINs
              already collected through our database.
            - Force a refresh: Always retrieve live data with the
              value 0.
            - Retrieve the total number of listings of this seller:
              the totalStorefrontAsinsCSV field of the seller object
              will be updated.

        wait : bool, optional
            Wait available token before doing effective query.
            Defaults to ``True``.

        Returns
        -------
        dict
            Dictionary containing one entry per input ``seller_id``.

        Examples
        --------
        Return the information from seller ``'A2L77EE7U53NWQ'``.

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> seller_info = api.seller_query("A2L77EE7U53NWQ", "US")
        >>> seller_info["A2L77EE7U53NWQ"]["sellerName"]
        'Amazon Warehouse'

        Notes
        -----
        Seller data is not available for Amazon China.

        """
        if isinstance(seller_id, list):
            if len(seller_id) > 100:
                err_str = "seller_id can contain at maximum 100 sellers"
                raise RuntimeError(err_str)
            seller = ",".join(seller_id)
        else:
            seller = seller_id

        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "seller": seller,
        }

        if storefront:
            payload["storefront"] = int(storefront)
        if update is not False:
            payload["update"] = update

        response = self._request("seller", payload, wait=wait)
        return _parse_seller(response["sellers"], to_datetime)

    def product_finder(
        self,
        product_parms: Union[Dict[str, Any], ProductParams],
        domain: Union[str, Domain] = "US",
        wait=True,
        n_products=50,
    ) -> List[str]:
        """Query the keepa product database to find products matching criteria.

        Almost all product fields can be searched for and sorted.

        Parameters
        ----------
        product_parms : dict, ProductParams
            Dictionary or :class:`keepa.ProductParams`.
        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.
        wait : bool, default: True
            Wait available token before doing effective query.
        n_products : int, default: 50
            Maximum number of matching products returned by keepa.

        Returns
        -------
        list[str]
            List of ASINs matching the product parameters.

        Notes
        -----
        When using the ``'sort'`` key in the ``product_parms`` parameter, use a
        compatible key along with the type of sort. For example:
        ``["current_SALES", "asc"]``

        Examples
        --------
        Query for the first 100 of Jim Butcher's books using the synchronous
        ``keepa.Keepa`` class. Sort by current sales.

        >>> import keepa
        >>> api = keepa.Keepa("<ENTER_ACTUAL_KEY_HERE>")
        >>> product_parms = {
        ...     "author": "jim butcher",
        ...     "sort": ["current_SALES", "asc"],
        ... }
        >>> asins = api.product_finder(product_parms, n_products=100)
        >>> asins
        ['B000HRMAR2',
         '0578799790',
         'B07PW1SVHM',
        ...
         'B003MXM744',
         '0133235750',
         'B01MXXLJPZ']

        Alternatively, use the :class:`keepa.ProductParams`:

        >>> product_parms = keepa.ProductParams(
        ...     author="jim butcher",
        ...     sort=["current_SALES", "asc"],
        ... )
        >>> asins = api.product_finder(product_parms, n_products=100)

        Query for all of Jim Butcher's books using the asynchronous
        ``keepa.AsyncKeepa`` class.

        >>> import asyncio
        >>> import keepa
        >>> product_parms = {"author": "jim butcher"}
        >>> async def main():
        ...     key = "<REAL_KEEPA_KEY>"
        ...     api = await keepa.AsyncKeepa().create(key)
        ...     return await api.product_finder(product_parms)
        ...
        >>> asins = asyncio.run(main())
        >>> asins
        ['B000HRMAR2',
         '0578799790',
         'B07PW1SVHM',
        ...
         'B003MXM744',
         '0133235750',
         'B01MXXLJPZ']

        """
        if isinstance(product_parms, dict):
            product_parms_valid = ProductParams(**product_parms)
        else:
            product_parms_valid = product_parms
        product_parms_dict = product_parms_valid.model_dump(exclude_none=True)
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "selection": json.dumps({**product_parms_dict, **{"perPage": n_products}}),
        }

        response = self._request("query", payload, wait=wait)
        return response["asinList"]

    def deals(self, deal_parms, domain: Union[str, Domain] = "US", wait=True) -> dict:
        """Query the Keepa API for product deals.

        You can find products that recently changed and match your
        search criteria.  A single request will return a maximum of
        150 deals.  Try out the deals page to first get accustomed to
        the options:
        https://keepa.com/#!deals

        For more details please visit:
        https://keepa.com/#!discuss/t/browsing-deals/338

        Parameters
        ----------
        deal_parms : dict
            Dictionary containing one or more of the following keys:

            - ``"page"``: int
            - ``"domainId"``: int
            - ``"excludeCategories"``: list
            - ``"includeCategories"``: list
            - ``"priceTypes"``: list
            - ``"deltaRange"``: list
            - ``"deltaPercentRange"``: list
            - ``"deltaLastRange"``: list
            - ``"salesRankRange"``: list
            - ``"currentRange"``: list
            - ``"minRating"``: int
            - ``"isLowest"``: bool
            - ``"isLowestOffer"``: bool
            - ``"isOutOfStock"``: bool
            - ``"titleSearch"``: String
            - ``"isRangeEnabled"``: bool
            - ``"isFilterEnabled"``: bool
            - ``"hasReviews"``: bool
            - ``"filterErotic"``: bool
            - ``"sortType"``: int
            - ``"dateRange"``: int

        domain : str | keepa.Domain, default: 'US'
            A valid Amazon domain. See :class:`keepa.Domain`.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Returns
        -------
        dict
            Dictionary containing the deals including the following keys:

            * ``'dr'`` - Ordered array of all deal objects matching your query.
            * ``'categoryIds'`` - Contains all root categoryIds of the matched
              deal products.
            * ``'categoryNames'`` - Contains all root category names of the
              matched deal products.
            * ``'categoryCount'`` - Contains how many deal products in the
              respective root category are found.

        Examples
        --------
        Return deals from category 16310101 using the synchronous
        ``keepa.Keepa`` class

        >>> import keepa
        >>> key = "<REAL_KEEPA_KEY>"
        >>> api = keepa.Keepa(key)
        >>> deal_parms = {
        ...     "page": 0,
        ...     "domainId": 1,
        ...     "excludeCategories": [1064954, 11091801],
        ...     "includeCategories": [16310101],
        ... }
        >>> deals = api.deals(deal_parms)

        Get the title of the first deal.

        >>> deals["dr"][0]["title"]
        'Orange Cream Rooibos, Tea Bags - Vanilla, Orange | Caffeine-Free,
        Antioxidant-rich, Hot & Iced | The Spice Hut, First Sip Of Tea'

        Conduct the same query with the asynchronous ``keepa.AsyncKeepa``
        class.

        >>> import asyncio
        >>> import keepa
        >>> deal_parms = {
        ...     "page": 0,
        ...     "domainId": 1,
        ...     "excludeCategories": [1064954, 11091801],
        ...     "includeCategories": [16310101],
        ... }
        >>> async def main():
        ...     key = "<REAL_KEEPA_KEY>"
        ...     api = await keepa.AsyncKeepa().create(key)
        ...     categories = await api.search_for_categories("movies")
        ...     return await api.deals(deal_parms)
        ...
        >>> asins = asyncio.run(main())
        >>> asins
        ['B0BF3P5XZS',
         'B08JQN5VDT',
         'B09SP8JPPK',
         '0999296345',
         'B07HPG684T',
         '1984825577',
        ...

        """
        # verify valid keys
        for key in deal_parms:
            if key not in DEAL_REQUEST_KEYS:
                raise ValueError(f'Invalid key "{key}"')

            # verify json type
            key_type = DEAL_REQUEST_KEYS[key]
            deal_parms[key] = key_type(deal_parms[key])

        deal_parms.setdefault("priceTypes", 0)

        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "selection": json.dumps(deal_parms),
        }

        return self._request("deal", payload, wait=wait)["deals"]

    def _request(self, request_type, payload, wait=True, raw_response=False):
        """Query keepa api server.

        Parses raw response from keepa into a json format. Handles errors and
        waits for available tokens if allowed.
        """
        if wait:
            self.wait_for_tokens()

        while True:
            raw = requests.get(
                f"https://api.keepa.com/{request_type}/?",
                payload,
                timeout=self._timeout,
            )
            status_code = str(raw.status_code)
            if status_code != "200":
                if status_code in SCODES:
                    if status_code == "429" and wait:
                        print("Response from server: %s" % SCODES[status_code])
                        self.wait_for_tokens()
                        continue
                    else:
                        raise RuntimeError(SCODES[status_code])
                else:
                    raise RuntimeError(f"REQUEST_FAILED: {status_code}")
            break

        response = raw.json()

        if "tokensConsumed" in response:
            log.debug("%d tokens consumed", response["tokensConsumed"])

        if "error" in response:
            if response["error"]:
                raise Exception(response["error"]["message"])

        # always update tokens
        self.tokens_left = response["tokensLeft"]

        if raw_response:
            return raw
        return response


class AsyncKeepa:
    r"""Class to support an asynchronous Python interface to keepa server.

    Initializes API with access key.  Access key can be obtained by
    signing up for a reoccurring or one time plan at:
    https://keepa.com/#!api

    Parameters
    ----------
    accesskey : str
        64 character access key string.

    timeout : float, optional
        Default timeout when issuing any request.  This is not a time
        limit on the entire response download; rather, an exception is
        raised if the server has not issued a response for timeout
        seconds.  Setting this to 0 disables the timeout, but will
        cause any request to hang indefiantly should keepa.com be down

    Examples
    --------
    Query for all of Jim Butcher's books using the asynchronous
    ``keepa.AsyncKeepa`` class.

    >>> import asyncio
    >>> import keepa
    >>> product_parms = {"author": "jim butcher"}
    >>> async def main():
    ...     key = "<REAL_KEEPA_KEY>"
    ...     api = await keepa.AsyncKeepa().create(key)
    ...     return await api.product_finder(product_parms)
    ...
    >>> asins = asyncio.run(main())
    >>> asins
    ['B000HRMAR2',
     '0578799790',
     'B07PW1SVHM',
    ...
     'B003MXM744',
     '0133235750',
     'B01MXXLJPZ']

    Query for product with ASIN ``'B0088PUEPK'`` using the asynchronous
    keepa interface.

    >>> import asyncio
    >>> import keepa
    >>> async def main():
    ...     key = "<REAL_KEEPA_KEY>"
    ...     api = await keepa.AsyncKeepa().create(key)
    ...     return await api.query("B0088PUEPK")
    ...
    >>> response = asyncio.run(main())
    >>> response[0]["title"]
    'Western Digital 1TB WD Blue PC Internal Hard Drive HDD - 7200 RPM,
    SATA 6 Gb/s, 64 MB Cache, 3.5" - WD10EZEX'

    """

    @classmethod
    async def create(cls, accesskey, timeout=10):
        """Create the async object."""
        self = AsyncKeepa()
        self.accesskey = accesskey
        self.status = None
        self.tokens_left = 0
        self._timeout = timeout

        # Store user's available tokens
        log.info("Connecting to keepa using key ending in %s", accesskey[-6:])
        await self.update_status()
        log.info("%d tokens remain", self.tokens_left)
        return self

    @property
    def time_to_refill(self):
        """Return the time to refill in seconds."""
        # Get current timestamp in milliseconds from UNIX epoch
        now = int(time.time() * 1000)
        timeatrefile = self.status["timestamp"] + self.status["refillIn"]

        # wait plus one second fudge factor
        timetorefil = timeatrefile - now + 1000
        if timetorefil < 0:
            timetorefil = 0

        # Account for negative tokens left
        if self.tokens_left < 0:
            timetorefil += (abs(self.tokens_left) / self.status["refillRate"]) * 60000

        # Return value in seconds
        return timetorefil / 1000.0

    async def update_status(self):
        """Update available tokens."""
        self.status = await self._request("token", {"key": self.accesskey}, wait=False)

    async def wait_for_tokens(self):
        """Check if there are any remaining tokens and waits if none are available."""
        await self.update_status()

        # Wait if no tokens available
        if self.tokens_left <= 0:
            tdelay = self.time_to_refill
            log.warning("Waiting %.0f seconds for additional tokens", tdelay)
            await asyncio.sleep(tdelay)
            await self.update_status()

    @is_documented_by(Keepa.query)
    async def query(
        self,
        items: Union[str, Sequence[str]],
        stats: Optional[Union[int]] = None,
        domain: str = "US",
        history: bool = True,
        offers: Optional[int] = None,
        update: Optional[int] = None,
        to_datetime: bool = True,
        rating: bool = False,
        out_of_stock_as_nan: bool = True,
        stock: bool = False,
        product_code_is_asin: bool = True,
        progress_bar: bool = True,
        buybox: bool = False,
        wait: bool = True,
        days: Optional[int] = None,
        only_live_offers: Optional[bool] = None,
        raw: bool = False,
    ):
        """Documented in Keepa.query."""
        if raw:
            raise ValueError("Raw response is only available in the non-async class")

        # Format items into numpy array
        try:
            items = format_items(items)
        except BaseException:
            raise Exception("Invalid product codes input")
        assert len(items), "No valid product codes"

        nitems = len(items)
        if nitems == 1:
            log.debug("Executing single product query")
        else:
            log.debug("Executing %d item product query", nitems)

        # check offer input
        if offers:
            if not isinstance(offers, int):
                raise TypeError('Parameter "offers" must be an interger')

            if offers > 100 or offers < 20:
                raise ValueError('Parameter "offers" must be between 20 and 100')

        # Report time to completion
        tcomplete = (
            float(nitems - self.tokens_left) / self.status["refillRate"]
            - (60000 - self.status["refillIn"]) / 60000.0
        )
        if tcomplete < 0.0:
            tcomplete = 0.5
        log.debug(
            "Estimated time to complete %d request(s) is %.2f minutes",
            nitems,
            tcomplete,
        )
        log.debug("\twith a refill rate of %d token(s) per minute", self.status["refillRate"])

        # product list
        products = []

        pbar = None
        if progress_bar:
            pbar = tqdm(total=nitems)

        # Number of requests is dependent on the number of items and
        # request limit.  Use available tokens first
        idx = 0  # or number complete
        while idx < nitems:
            nrequest = nitems - idx

            # cap request
            if nrequest > REQUEST_LIMIT:
                nrequest = REQUEST_LIMIT

            # request from keepa and increment current position
            item_request = items[idx : idx + nrequest]  # noqa: E203
            response = await self._product_query(
                item_request,
                product_code_is_asin,
                stats=stats,
                domain=domain,
                stock=stock,
                offers=offers,
                update=update,
                history=history,
                rating=rating,
                to_datetime=to_datetime,
                out_of_stock_as_nan=out_of_stock_as_nan,
                buybox=buybox,
                wait=wait,
                days=days,
                only_live_offers=only_live_offers,
            )
            idx += nrequest
            products.extend(response["products"])

            if pbar is not None:
                pbar.update(nrequest)

        return products

    @is_documented_by(Keepa._product_query)
    async def _product_query(self, items, product_code_is_asin=True, **kwargs):
        """Documented in Keepa._product_query."""
        # ASINs convert to comma joined string
        assert len(items) <= 100

        if product_code_is_asin:
            kwargs["asin"] = ",".join(items)
        else:
            kwargs["code"] = ",".join(items)

        kwargs["key"] = self.accesskey
        kwargs["domain"] = _domain_to_dcode(kwargs["domain"])

        # Convert bool values to 0 and 1.
        kwargs["stock"] = int(kwargs["stock"])
        kwargs["history"] = int(kwargs["history"])
        kwargs["rating"] = int(kwargs["rating"])
        kwargs["buybox"] = int(kwargs["buybox"])

        if kwargs["update"] is None:
            del kwargs["update"]
        else:
            kwargs["update"] = int(kwargs["update"])

        if kwargs["offers"] is None:
            del kwargs["offers"]
        else:
            kwargs["offers"] = int(kwargs["offers"])

        if kwargs["only_live_offers"] is None:
            del kwargs["only_live_offers"]
        else:
            kwargs["only-live-offers"] = int(kwargs.pop("only_live_offers"))
            # Keepa's param actually doesn't use snake_case.
            # I believe using snake case throughout the Keepa interface is better.

        if kwargs["days"] is None:
            del kwargs["days"]
        else:
            assert kwargs["days"] > 0

        if kwargs["stats"] is None:
            del kwargs["stats"]

        out_of_stock_as_nan = kwargs.pop("out_of_stock_as_nan", True)
        to_datetime = kwargs.pop("to_datetime", True)

        # Query and replace csv with parsed data if history enabled
        wait = kwargs.get("wait")
        kwargs.pop("wait", None)
        response = await self._request("product", kwargs, wait=wait)
        if kwargs["history"]:
            for product in response["products"]:
                if product["csv"]:  # if data exists
                    product["data"] = parse_csv(product["csv"], to_datetime, out_of_stock_as_nan)

        if kwargs.get("stats", None):
            for product in response["products"]:
                stats = product.get("stats", None)
                if stats:
                    product["stats_parsed"] = _parse_stats(stats, to_datetime)

        return response

    @is_documented_by(Keepa.best_sellers_query)
    async def best_sellers_query(
        self, category, rank_avg_range=0, domain: Union[str, Domain] = "US", wait=True
    ):
        """Documented by Keepa.best_sellers_query."""
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "category": category,
            "range": rank_avg_range,
        }

        response = await self._request("bestsellers", payload, wait=wait)
        if "bestSellersList" in response:
            return response["bestSellersList"]["asinList"]
        else:  # pragma: no cover
            log.info("Best sellers search results not yet available")

    @is_documented_by(Keepa.search_for_categories)
    async def search_for_categories(self, searchterm, domain: Union[str, Domain] = "US", wait=True):
        """Documented by Keepa.search_for_categories."""
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "type": "category",
            "term": searchterm,
        }

        response = await self._request("search", payload, wait=wait)
        if response["categories"] == {}:  # pragma no cover
            raise Exception(
                "Categories search results not yet available " + "or no search terms found."
            )
        else:
            return response["categories"]

    @is_documented_by(Keepa.category_lookup)
    async def category_lookup(
        self, category_id, domain: Union[str, Domain] = "US", include_parents=0, wait=True
    ):
        """Documented by Keepa.category_lookup."""
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "category": category_id,
            "parents": include_parents,
        }

        response = await self._request("category", payload, wait=wait)
        if response["categories"] == {}:  # pragma no cover
            raise Exception("Category lookup results not yet available or no" + "match found.")
        else:
            return response["categories"]

    @is_documented_by(Keepa.seller_query)
    async def seller_query(
        self,
        seller_id,
        domain: Union[str, Domain] = "US",
        to_datetime=True,
        storefront=False,
        update=None,
        wait=True,
    ):
        """Documented by Keepa.sellerer_query."""
        if isinstance(seller_id, list):
            if len(seller_id) > 100:
                err_str = "seller_id can contain at maximum 100 sellers"
                raise RuntimeError(err_str)
            seller = ",".join(seller_id)
        else:
            seller = seller_id

        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "seller": seller,
        }

        if storefront:
            payload["storefront"] = int(storefront)
        if update:
            payload["update"] = update

        response = await self._request("seller", payload, wait=wait)
        return _parse_seller(response["sellers"], to_datetime)

    @is_documented_by(Keepa.product_finder)
    async def product_finder(
        self,
        product_parms: Union[Dict[str, Any], ProductParams],
        domain: Union[str, Domain] = "US",
        wait=True,
        n_products=50,
    ) -> List[str]:
        """Documented by Keepa.product_finder."""
        if isinstance(product_parms, dict):
            product_parms_valid = ProductParams(**product_parms)
        else:
            product_parms_valid = product_parms
        product_parms_dict = product_parms_valid.model_dump(exclude_none=True)
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "selection": json.dumps({**product_parms_dict, **{"perPage": n_products}}),
        }

        response = await self._request("query", payload, wait=wait)
        return response["asinList"]

    @is_documented_by(Keepa.deals)
    async def deals(self, deal_parms, domain: Union[str, Domain] = "US", wait=True):
        """Documented in Keepa.deals."""
        # verify valid keys
        for key in deal_parms:
            if key not in DEAL_REQUEST_KEYS:
                raise ValueError(f'Invalid key "{key}"')

            # verify json type
            key_type = DEAL_REQUEST_KEYS[key]
            deal_parms[key] = key_type(deal_parms[key])

        deal_parms.setdefault("priceTypes", 0)

        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "selection": json.dumps(deal_parms),
        }

        deals = await self._request("deal", payload, wait=wait)
        return deals["deals"]

    async def _request(self, request_type, payload, wait=True):
        """Documented in Keepa._request."""
        while True:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.keepa.com/{request_type}/?",
                    params=payload,
                    timeout=self._timeout,
                ) as raw:
                    status_code = str(raw.status)
                    if status_code != "200":
                        if status_code in SCODES:
                            if status_code == "429" and wait:
                                await self.wait_for_tokens()
                                continue
                            else:
                                raise Exception(SCODES[status_code])
                        else:
                            raise Exception("REQUEST_FAILED")

                    response = await raw.json()

                    if "error" in response:
                        if response["error"]:
                            raise Exception(response["error"]["message"])

                    # always update tokens
                    self.tokens_left = response["tokensLeft"]
                    return response
            break


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


def _str_to_bool(string: str):
    if string:
        return bool(int(string))
    return False


def process_used_buybox(buybox_info: List[str]) -> pd.DataFrame:
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
