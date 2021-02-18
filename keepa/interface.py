"""Interface module to download Amazon product and history data from
keepa.com
"""

from tqdm import tqdm
import aiohttp
import asyncio
import datetime
import json
import logging
import numpy as np
import pandas as pd
import time

from keepa.query_keys import DEAL_REQUEST_KEYS, PRODUCT_REQUEST_KEYS

log = logging.getLogger(__name__)
log.setLevel('DEBUG')

# hardcoded ordinal time from
KEEPA_ST_ORDINAL = np.datetime64('2011-01-01')

# Request limit
REQUEST_LIMIT = 100

# Status code dictionary/key
SCODES = {'400': 'REQUEST_REJECTED',
          '402': 'PAYMENT_REQUIRED',
          '405': 'METHOD_NOT_ALLOWED',
          '429': 'NOT_ENOUGH_TOKEN'}

# domain codes
# Valid values: [ 1: com | 2: co.uk | 3: de | 4: fr | 5:
#                 co.jp | 6: ca | 7: cn | 8: it | 9: es | 10: in | 11: com.mx ]
DCODES = ['RESERVED', 'US', 'GB', 'DE', 'FR', 'JP', 'CA', 'CN', 'IT', 'ES',
          'IN', 'MX']

# csv indices. used when parsing csv and stats fields.
# https://github.com/keepacom/api_backend
    # see api_backend/src/main/java/com/keepa/api/backend/structs/Product.java
    # [index in csv, key name, isfloat(is price or rating)]
csv_indices = [[0, 'AMAZON', True],
               [1, 'NEW', True],
               [2, 'USED', True],
               [3, 'SALES', False],
               [4, 'LISTPRICE', True],
               [5, 'COLLECTIBLE', True],
               [6, 'REFURBISHED', True],
               [7, 'NEW_FBM_SHIPPING', True],
               [8, 'LIGHTNING_DEAL', True],
               [9, 'WAREHOUSE', True],
               [10, 'NEW_FBA', True],
               [11, 'COUNT_NEW', False],
               [12, 'COUNT_USED', False],
               [13, 'COUNT_REFURBISHED', False],
               [14, 'CollectableOffers', False],
               [15, 'EXTRA_INFO_UPDATES', False],
               [16, 'RATING', True],
               [17, 'COUNT_REVIEWS', False],
               [18, 'BUY_BOX_SHIPPING', True],
               [19, 'USED_NEW_SHIPPING', True],
               [20, 'USED_VERY_GOOD_SHIPPING', True],
               [21, 'USED_GOOD_SHIPPING', True],
               [22, 'USED_ACCEPTABLE_SHIPPING', True],
               [23, 'COLLECTIBLE_NEW_SHIPPING', True],
               [24, 'COLLECTIBLE_VERY_GOOD_SHIPPING', True],
               [25, 'COLLECTIBLE_GOOD_SHIPPING', True],
               [26, 'COLLECTIBLE_ACCEPTABLE_SHIPPING', True],
               [27, 'REFURBISHED_SHIPPING', True],
               [28, 'EBAY_NEW_SHIPPING', True],
               [29, 'EBAY_USED_SHIPPING', True],
               [30, 'TRADE_IN', True],
               [31, 'RENT', False]]


def _parse_stats(stats, to_datetime):
    stats_parsed = {}

    for stat_key, stat_value in stats.items():
        if isinstance(stat_value, int) and stat_value < 0:  # -1 or -2 means not exist. 0 doesn't mean not exist.
            stat_value = None

        if stat_value is not None:
            if stat_key == 'lastOffersUpdate':
                stats_parsed[stat_key] = keepa_minutes_to_time([stat_value], to_datetime)[0]
            elif isinstance(stat_value, list) and len(stat_value) > 0:
                stat_value_dict = {}
                convert_time_in_value_pair = any(map(lambda v: v is not None and isinstance(v, list), stat_value))

                for ind, key, isfloat in csv_indices:
                    stat_value_item = stat_value[ind] if ind < len(stat_value) else None

                    def normalize_value(v):
                        if v < 0:
                            return None

                        if isfloat:
                            v = float(v) / 100
                            if key == 'RATING':
                                v = v * 10

                        return v

                    if stat_value_item is not None:
                        if convert_time_in_value_pair:
                            stat_value_time, stat_value_item = stat_value_item
                            stat_value_item = normalize_value(stat_value_item)
                            if stat_value_item is not None:
                                stat_value_time = keepa_minutes_to_time([stat_value_time], to_datetime)[0]
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


_seller_time_data_keys = ['trackedSince', 'lastUpdate']

def _parse_seller(seller_raw_response, to_datetime):
    sellers = list(seller_raw_response.values())
    for seller in sellers:

        def convert_time_data(key):
            date_val = seller.get(key, None)
            if date_val is not None:
                return (key, keepa_minutes_to_time([date_val], to_datetime)[0])
            else:
                return None

        seller.update(filter(lambda p: p is not None, map(convert_time_data, _seller_time_data_keys)))

    return dict(map(lambda seller: (seller['sellerId'], seller), sellers))


def parse_csv(csv, to_datetime=True, out_of_stock_as_nan=True):
    """Parses csv list from keepa into a python dictionary.

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
            if 'SHIPPING' in key:  # shipping price is included
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
                values = values.astype(np.float)/100
                if out_of_stock_as_nan:
                    values[nan_mask] = np.nan

                if key == 'RATING':
                    values *= 10

            timeval = keepa_minutes_to_time(times, to_datetime)

            product_data['%s_time' % key] = timeval
            product_data[key] = values

            # combine time and value into a data frame using time as index
            product_data['df_%s' % key] = pd.DataFrame({'value': values}, index=timeval)

    return product_data


def format_items(items):
    """ Checks if the input items are valid and formats them """
    if isinstance(items, list) or isinstance(items, np.ndarray):
        return np.unique(items)
    elif isinstance(items, str):
        return np.asarray([items])


class AsyncKeepa():
    """Class to support a Python interface to keepa server.

    Initializes API with access key.  Access key can be obtained by
    signing up for a reoccurring or one time plan at:
    https://keepa.com/#!api

    Parameters
    ----------
    accesskey : str
        64 character access key string.

    Examples
    --------
    Create the api object

    >>> import keepa
    >>> mykey = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    >>> api = await keepa.AsyncKeepa.create(mykey)

    Request data from two ASINs

    >>> products = await api.query(['0439064872', '1426208081'])

    Print item details

    >>> print('Item 1')
    >>> print('\t ASIN: {:s}'.format(products[0]['asin']))
    >>> print('\t Title: {:s}'.format(products[0]['title']))

    Print item price

    >>> usedprice = products[0]['data']['MarketplaceUsed']
    >>> usedtimes = products[0]['data']['MarketplaceUsed_time']
    >>> print('\t Used price: ${:.2f}'.format(usedprice[-1]))
    >>> print('\t as of: {:s}'.format(str(usedtimes[-1])))
    """

    @classmethod
    async def create(cls, accesskey):
        self = AsyncKeepa()
        self.accesskey = accesskey
        self.status = None
        self.tokens_left = 0

        # Store user's available tokens
        log.info('Connecting to keepa using key ending in %s' % accesskey[-6:])
        await self.update_status()
        log.info('%d tokens remain' % self.tokens_left)

        return self

    @property
    def time_to_refill(self):
        """ Returns the time to refill in seconds """
        # Get current timestamp in miliseconds from unix epoch
        now = int(time.time() * 1000)
        timeatrefile = self.status['timestamp'] + self.status['refillIn']

        # wait plus one second fudge factor
        timetorefil = timeatrefile - now + 1000
        if timetorefil < 0:
            timetorefil = 0

        # Account for negative tokens left
        if self.tokens_left < 0:
            timetorefil += (abs(self.tokens_left) / self.status['refillRate']) * 60000

        # Return value in seconds
        return timetorefil / 1000.0

    async def update_status(self):
        """ Updates available tokens """
        self.status = await self._request('token', {'key': self.accesskey}, wait=False)

    async def wait_for_tokens(self):
        """Checks any remaining tokens and waits if none are available.  """
        await self.update_status()

        # Wait if no tokens available
        if self.tokens_left <= 0:
            tdelay = self.time_to_refill
            log.warning('Waiting %.0f seconds for additional tokens' % tdelay)
            await asyncio.sleep(tdelay)
            await self.update_status()

    async def query(self, items, stats=None, domain='US', history=True,
                    offers=None, update=None, to_datetime=True,
                    rating=False, out_of_stock_as_nan=True, stock=False,
                    product_code_is_asin=True, progress_bar=True, buybox=False,
                    wait=True):
        """ Performs a product query of a list, array, or single ASIN.
        Returns a list of product data with one entry for each
        product.

        Parameters
        ----------
        items : str, list, np.ndarray
            A list, array, or single asin, UPC, EAN, or ISBN-13
            identifying a product.  ASINs should be 10 characters and
            match a product on Amazon.  Items not matching Amazon
            product or duplicate Items will return no data.  When
            using non-ASIN items, set product_code_is_asin to False

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

        domain : str, optional
            One of the following Amazon domains: RESERVED, US, GB, DE,
            FR, JP, CA, CN, IT, ES, IN, MX Defaults to US.

        offers : int, optional
            Adds available offers to product data.  Default 0.  Must
            be between 20 and 100.

        update : int, optional
            if data is older than the input integer, keepa will
            update their database and return live data.  If set to 0
            (live data), request may cost an additional token.
            Default None

        history : bool, optional
            When set to True includes the price, sales, and offer
            history of a product.  Set to False to reduce request time
            if data is not required.  Default True

        rating : bool, optional
            When set to to True, includes the existing RATING and
            COUNT_REVIEWS history of the csv field.  Default False

        to_datetime : bool, optional
            Modifies numpy minutes to datetime.datetime values.
            Default True.

        out_of_stock_as_nan : bool, optional
            When True, prices are NAN when price category is out of
            stock.  When False, prices are -0.01 Default True

        stock : bool, optional
            Can only be used if the offers parameter is also True. If
            True, the stock will be collected for all retrieved live
            offers. Note: We can only determine stock up 10 qty. Stock
            retrieval takes additional time, expect the request to
            take longer. Existing stock history will be included
            whether or not the stock parameter is used.

        product_code_is_asin : bool, optional
            The type of product code you are requesting. True when
            product code is an ASIN, an Amazon standard identification
            number, or 'code', for UPC, EAN, or ISBN-13 codes.

        progress_bar : bool, optional
            Display a progress bar using ``tqdm``.  Defaults to
            ``True``.

        buybox : bool, optional
            Additional token cost: 2 per product). When true the
            product and statistics object will include all available
            buy box related data:

            - current price, price history, and statistical values
            - buyBoxSellerIdHistory
            - all buy box fields in the statistics object

            The buybox parameter
            does not trigger a fresh data collection. If the offers
            parameter is used the buybox parameter is ignored, as the
            offers parameter also provides access to all buy box
            related data. To access the statistics object the stats
            parameter is required.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Returns
        -------
        products : list

            See: https://keepa.com/#!discuss/t/product-object/116

            List of products.  Each product within the list is a
            dictionary.  The keys of each item may vary, so see the
            keys within each product for further details.

            Each product should contain at a minimum a "data" key
            containing a formatted dictionary.  For the available
            fields see the notes section

        Notes
        -----
        The following are data fields a product dictionary

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
        """
        # Format items into numpy array
        try:
            items = format_items(items)
        except BaseException:
            raise Exception('Invalid product codes input')
        assert len(items), 'No valid product codes'

        nitems = len(items)
        if nitems == 1:
            log.debug('Executing single product query')
        else:
            log.debug('Executing %d item product query', nitems)

        # check offer input
        if offers:
            assert isinstance(offers, int), 'Parameter "offers" must be an interger'

            if offers > 100 or offers < 20:
                raise ValueError('Parameter "offers" must be between 20 and 100')

        # Report time to completion
        tcomplete = float(nitems - self.tokens_left) / self.status['refillRate'] - (
            60000 - self.status['refillIn']) / 60000.0
        if tcomplete < 0.0:
            tcomplete = 0.5
        log.debug('Estimated time to complete %d request(s) is %.2f minutes' %
                  (nitems, tcomplete))
        log.debug('\twith a refill rate of %d token(s) per minute' %
                  self.status['refillRate'])

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
            item_request = items[idx:idx + nrequest]
            response = await self._product_query(
                item_request,
                product_code_is_asin,
                stats=stats,
                domain=domain, stock=stock,
                offers=offers, update=update,
                history=history, rating=rating,
                to_datetime=to_datetime,
                out_of_stock_as_nan=out_of_stock_as_nan,
                buybox=buybox,
                wait=wait)
            idx += nrequest
            products.extend(response['products'])

            if pbar is not None:
                pbar.update(nrequest)

        return products

    async def _product_query(self, items, product_code_is_asin=True, **kwargs):
        """
        Sends query to keepa server and returns parsed JSON result.

        Parameters
        ----------
        items : np.ndarray
            Array of asins.  If UPC, EAN, or ISBN-13, as_asin must be
            False.  Must be between 1 and 100 ASINs

        as_asin : bool, optional
            Interpret product codes as ASINs only.

        stats : int or date format
            Set the stats time for get sales rank inside this range

        domain : str
            One of the following Amazon domains:
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX

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
            Time in miliseconds to the next refill of tokens.

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
            kwargs['asin'] = ','.join(items)
        else:
            kwargs['code'] = ','.join(items)

        kwargs['key'] = self.accesskey
        kwargs['domain'] = DCODES.index(kwargs['domain'])
        kwargs['stock'] = int(kwargs['stock'])
        kwargs['history'] = int(kwargs['history'])
        kwargs['rating'] = int(kwargs['rating'])
        kwargs['buybox'] = int(kwargs['buybox'])

        if kwargs['update'] is None:
            del kwargs['update']
        else:
            kwargs['update'] = int(kwargs['update'])

        if kwargs['offers'] is None:
            del kwargs['offers']
        else:
            kwargs['offers'] = int(kwargs['offers'])

        if kwargs['stats'] is None:
            del kwargs['stats']

        kwargs['rating'] = int(kwargs['rating'])
        out_of_stock_as_nan = kwargs.pop('out_of_stock_as_nan', True)
        to_datetime = kwargs.pop('to_datetime', True)

        # Query and replace csv with parsed data if history enabled
        wait = kwargs.get("wait")
        kwargs.pop("wait", None)
        response = await self._request('product', kwargs, wait=wait)
        if kwargs['history']:
            for product in response['products']:
                if product['csv']:  # if data exists
                    product['data'] = parse_csv(product['csv'],
                                                to_datetime,
                                                out_of_stock_as_nan)

        if kwargs.get('stats', None):
            for product in response['products']:
                stats = product.get('stats', None)
                if stats:
                    product['stats_parsed'] = _parse_stats(stats, to_datetime)

        return response

    async def best_sellers_query(self, category, rank_avg_range=0, domain='US', wait=True):
        """
        Retrieve an ASIN list of the most popular products based on
        sales in a specific category or product group.  See
        "search_for_categories" for information on how to get a
        category.

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
            via the category search "search_for_categories"

        domain : str
            Amazon locale you want to access. Must be one of the following
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
            Default US

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Returns
        -------
        best_sellers : list
            List of best seller ASINs
        """
        assert domain in DCODES, 'Invalid domain code'

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'category': category,
                   'range': rank_avg_range}

        response = await self._request('bestsellers', payload, wait=wait)
        if 'bestSellersList' in response:
            return response['bestSellersList']['asinList']
        else:  # pragma: no cover
            log.info('Best sellers search results not yet available')

    async def search_for_categories(self, searchterm, domain='US', wait=True):
        """
        Searches for categories from Amazon.

        Parameters
        ----------
        searchterm : str
            Input search term.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Returns
        -------
        categories : list
            The response contains a categories list with all matching
            categories.

        Examples
        --------
        Print all categories from science

        >>> categories = await api.search_for_categories('science')
        >>> for cat_id in categories:
        >>>    print(cat_id, categories[cat_id]['name'])

        """
        assert domain in DCODES, 'Invalid domain code'

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'type': 'category',
                   'term': searchterm}

        response = await self._request('search', payload, wait=wait)
        if response['categories'] == {}:  # pragma no cover
            raise Exception('Categories search results not yet available ' +
                            'or no search terms found.')
        else:
            return response['categories']

    async def category_lookup(self, category_id, domain='US', include_parents=0, wait=True):
        """
        Return root categories given a categoryId.

        Parameters
        ----------
        category_id : int
            ID for specific category or 0 to return a list of root
            categories.

        domain : str
            Amazon locale you want to access. Must be one of the following
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
            Default US

        include_parents : int
            Include parents.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Returns
        -------
        categories : list
            Output format is the same as search_for_categories.

        Examples
        --------
        Use 0 to return all root categories
        >>> categories = await api.category_lookup(0)

        Print all root categories
        >>> for cat_id in categories:
        >>>    print(cat_id, categories[cat_id]['name'])
        """
        assert domain in DCODES, 'Invalid domain code'

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'category': category_id,
                   'parents': include_parents}

        response = await self._request('category', payload, wait=wait)
        if response['categories'] == {}:  # pragma no cover
            raise Exception('Category lookup results not yet available or no' +
                            'match found.')
        else:
            return response['categories']

    async def seller_query(self, seller_id, domain='US', to_datetime=True, 
                           storefront=False, update=None, wait=True):
        """Receives seller information for a given seller id.  If a
        seller is not found no tokens will be consumed.

        Token cost: 1 per requested seller

        Parameters
        ----------
        seller_id : str or list
            The seller id of the merchant you want to request. For
            batch requests, you may submit a list of 100 seller_ids.
            The seller id can also be found on Amazon on seller
            profile pages in the seller parameter of the URL as well
            as in the offers results from a product query.

        domain : str, optional
            One of the following Amazon domains: RESERVED, US, GB, DE,
            FR, JP, CA, CN, IT, ES, IN, MX Defaults to US.

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

            - Retrieve data from Amazon: a storefront ASIN list containing
              up to 2,400 ASINs, in addition to all ASINs already collected
              through our database.
            - Force a refresh: Always retrieve live data with the value 0.
            - Retrieve the total number of listings of this seller: the
              totalStorefrontAsinsCSV field of the seller object will be
              updated.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Returns
        -------
        seller_info : dict
            Dictionary containing one entry per input seller_id.

        Examples
        --------
        >>> seller_info = await api.seller_query('A2L77EE7U53NWQ', 'US')

        Notes
        -----
        Seller data is not available for Amazon China.
        """
        if isinstance(seller_id, list):
            if len(seller_id) > 100:
                err_str = 'seller_id can contain at maximum 100 sellers'
                raise RuntimeError(err_str)
            seller = ','.join(seller_id)
        else:
            seller = seller_id

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'seller': seller}

        if storefront:
            payload["storefront"] = int(storefront)
        if update:
            payload["update"] = update

        response = await self._request('seller', payload, wait=wait)
        return _parse_seller(response['sellers'], to_datetime)

    async def product_finder(self, product_parms, domain='US', wait=True):
        """Query the keepa product database to find products matching
        your criteria. Almost all product fields can be searched for
        and sorted by.

        Parameters
        ----------
        product_parms : dict
            Dictionary containing one or more of the following keys:

            - ``'author': str``
            - ``'availabilityAmazon': int``
            - ``'avg180_AMAZON_lte': int``
            - ``'avg180_AMAZON_gte': int``
            - ``'avg180_BUY_BOX_SHIPPING_lte': int``
            - ``'avg180_BUY_BOX_SHIPPING_gte': int``
            - ``'avg180_COLLECTIBLE_lte': int``
            - ``'avg180_COLLECTIBLE_gte': int``
            - ``'avg180_COUNT_COLLECTIBLE_lte': int``
            - ``'avg180_COUNT_COLLECTIBLE_gte': int``
            - ``'avg180_COUNT_NEW_lte': int``
            - ``'avg180_COUNT_NEW_gte': int``
            - ``'avg180_COUNT_REFURBISHED_lte': int``
            - ``'avg180_COUNT_REFURBISHED_gte': int``
            - ``'avg180_COUNT_REVIEWS_lte': int``
            - ``'avg180_COUNT_REVIEWS_gte': int``
            - ``'avg180_COUNT_USED_lte': int``
            - ``'avg180_COUNT_USED_gte': int``
            - ``'avg180_EBAY_NEW_SHIPPING_lte': int``
            - ``'avg180_EBAY_NEW_SHIPPING_gte': int``
            - ``'avg180_EBAY_USED_SHIPPING_lte': int``
            - ``'avg180_EBAY_USED_SHIPPING_gte': int``
            - ``'avg180_LIGHTNING_DEAL_lte': int``
            - ``'avg180_LIGHTNING_DEAL_gte': int``
            - ``'avg180_LISTPRICE_lte': int``
            - ``'avg180_LISTPRICE_gte': int``
            - ``'avg180_NEW_lte': int``
            - ``'avg180_NEW_gte': int``
            - ``'avg180_NEW_FBA_lte': int``
            - ``'avg180_NEW_FBA_gte': int``
            - ``'avg180_NEW_FBM_SHIPPING_lte': int``
            - ``'avg180_NEW_FBM_SHIPPING_gte': int``
            - ``'avg180_RATING_lte': int``
            - ``'avg180_RATING_gte': int``
            - ``'avg180_REFURBISHED_lte': int``
            - ``'avg180_REFURBISHED_gte': int``
            - ``'avg180_REFURBISHED_SHIPPING_lte': int``
            - ``'avg180_REFURBISHED_SHIPPING_gte': int``
            - ``'avg180_RENT_lte': int``
            - ``'avg180_RENT_gte': int``
            - ``'avg180_SALES_lte': int``
            - ``'avg180_SALES_gte': int``
            - ``'avg180_TRADE_IN_lte': int``
            - ``'avg180_TRADE_IN_gte': int``
            - ``'avg180_USED_lte': int``
            - ``'avg180_USED_gte': int``
            - ``'avg180_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'avg180_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'avg180_USED_GOOD_SHIPPING_lte': int``
            - ``'avg180_USED_GOOD_SHIPPING_gte': int``
            - ``'avg180_USED_NEW_SHIPPING_lte': int``
            - ``'avg180_USED_NEW_SHIPPING_gte': int``
            - ``'avg180_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'avg180_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'avg180_WAREHOUSE_lte': int``
            - ``'avg180_WAREHOUSE_gte': int``
            - ``'avg1_AMAZON_lte': int``
            - ``'avg1_AMAZON_gte': int``
            - ``'avg1_BUY_BOX_SHIPPING_lte': int``
            - ``'avg1_BUY_BOX_SHIPPING_gte': int``
            - ``'avg1_COLLECTIBLE_lte': int``
            - ``'avg1_COLLECTIBLE_gte': int``
            - ``'avg1_COUNT_COLLECTIBLE_lte': int``
            - ``'avg1_COUNT_COLLECTIBLE_gte': int``
            - ``'avg1_COUNT_NEW_lte': int``
            - ``'avg1_COUNT_NEW_gte': int``
            - ``'avg1_COUNT_REFURBISHED_lte': int``
            - ``'avg1_COUNT_REFURBISHED_gte': int``
            - ``'avg1_COUNT_REVIEWS_lte': int``
            - ``'avg1_COUNT_REVIEWS_gte': int``
            - ``'avg1_COUNT_USED_lte': int``
            - ``'avg1_COUNT_USED_gte': int``
            - ``'avg1_EBAY_NEW_SHIPPING_lte': int``
            - ``'avg1_EBAY_NEW_SHIPPING_gte': int``
            - ``'avg1_EBAY_USED_SHIPPING_lte': int``
            - ``'avg1_EBAY_USED_SHIPPING_gte': int``
            - ``'avg1_LIGHTNING_DEAL_lte': int``
            - ``'avg1_LIGHTNING_DEAL_gte': int``
            - ``'avg1_LISTPRICE_lte': int``
            - ``'avg1_LISTPRICE_gte': int``
            - ``'avg1_NEW_lte': int``
            - ``'avg1_NEW_gte': int``
            - ``'avg1_NEW_FBA_lte': int``
            - ``'avg1_NEW_FBA_gte': int``
            - ``'avg1_NEW_FBM_SHIPPING_lte': int``
            - ``'avg1_NEW_FBM_SHIPPING_gte': int``
            - ``'avg1_RATING_lte': int``
            - ``'avg1_RATING_gte': int``
            - ``'avg1_REFURBISHED_lte': int``
            - ``'avg1_REFURBISHED_gte': int``
            - ``'avg1_REFURBISHED_SHIPPING_lte': int``
            - ``'avg1_REFURBISHED_SHIPPING_gte': int``
            - ``'avg1_RENT_lte': int``
            - ``'avg1_RENT_gte': int``
            - ``'avg1_SALES_lte': int``
            - ``'avg1_SALES_lte': int``
            - ``'avg1_SALES_gte': int``
            - ``'avg1_TRADE_IN_lte': int``
            - ``'avg1_TRADE_IN_gte': int``
            - ``'avg1_USED_lte': int``
            - ``'avg1_USED_gte': int``
            - ``'avg1_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'avg1_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'avg1_USED_GOOD_SHIPPING_lte': int``
            - ``'avg1_USED_GOOD_SHIPPING_gte': int``
            - ``'avg1_USED_NEW_SHIPPING_lte': int``
            - ``'avg1_USED_NEW_SHIPPING_gte': int``
            - ``'avg1_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'avg1_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'avg1_WAREHOUSE_lte': int``
            - ``'avg1_WAREHOUSE_gte': int``
            - ``'avg30_AMAZON_lte': int``
            - ``'avg30_AMAZON_gte': int``
            - ``'avg30_BUY_BOX_SHIPPING_lte': int``
            - ``'avg30_BUY_BOX_SHIPPING_gte': int``
            - ``'avg30_COLLECTIBLE_lte': int``
            - ``'avg30_COLLECTIBLE_gte': int``
            - ``'avg30_COUNT_COLLECTIBLE_lte': int``
            - ``'avg30_COUNT_COLLECTIBLE_gte': int``
            - ``'avg30_COUNT_NEW_lte': int``
            - ``'avg30_COUNT_NEW_gte': int``
            - ``'avg30_COUNT_REFURBISHED_lte': int``
            - ``'avg30_COUNT_REFURBISHED_gte': int``
            - ``'avg30_COUNT_REVIEWS_lte': int``
            - ``'avg30_COUNT_REVIEWS_gte': int``
            - ``'avg30_COUNT_USED_lte': int``
            - ``'avg30_COUNT_USED_gte': int``
            - ``'avg30_EBAY_NEW_SHIPPING_lte': int``
            - ``'avg30_EBAY_NEW_SHIPPING_gte': int``
            - ``'avg30_EBAY_USED_SHIPPING_lte': int``
            - ``'avg30_EBAY_USED_SHIPPING_gte': int``
            - ``'avg30_LIGHTNING_DEAL_lte': int``
            - ``'avg30_LIGHTNING_DEAL_gte': int``
            - ``'avg30_LISTPRICE_lte': int``
            - ``'avg30_LISTPRICE_gte': int``
            - ``'avg30_NEW_lte': int``
            - ``'avg30_NEW_gte': int``
            - ``'avg30_NEW_FBA_lte': int``
            - ``'avg30_NEW_FBA_gte': int``
            - ``'avg30_NEW_FBM_SHIPPING_lte': int``
            - ``'avg30_NEW_FBM_SHIPPING_gte': int``
            - ``'avg30_RATING_lte': int``
            - ``'avg30_RATING_gte': int``
            - ``'avg30_REFURBISHED_lte': int``
            - ``'avg30_REFURBISHED_gte': int``
            - ``'avg30_REFURBISHED_SHIPPING_lte': int``
            - ``'avg30_REFURBISHED_SHIPPING_gte': int``
            - ``'avg30_RENT_lte': int``
            - ``'avg30_RENT_gte': int``
            - ``'avg30_SALES_lte': int``
            - ``'avg30_SALES_gte': int``
            - ``'avg30_TRADE_IN_lte': int``
            - ``'avg30_TRADE_IN_gte': int``
            - ``'avg30_USED_lte': int``
            - ``'avg30_USED_gte': int``
            - ``'avg30_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'avg30_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'avg30_USED_GOOD_SHIPPING_lte': int``
            - ``'avg30_USED_GOOD_SHIPPING_gte': int``
            - ``'avg30_USED_NEW_SHIPPING_lte': int``
            - ``'avg30_USED_NEW_SHIPPING_gte': int``
            - ``'avg30_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'avg30_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'avg30_WAREHOUSE_lte': int``
            - ``'avg30_WAREHOUSE_gte': int``
            - ``'avg7_AMAZON_lte': int``
            - ``'avg7_AMAZON_gte': int``
            - ``'avg7_BUY_BOX_SHIPPING_lte': int``
            - ``'avg7_BUY_BOX_SHIPPING_gte': int``
            - ``'avg7_COLLECTIBLE_lte': int``
            - ``'avg7_COLLECTIBLE_gte': int``
            - ``'avg7_COUNT_COLLECTIBLE_lte': int``
            - ``'avg7_COUNT_COLLECTIBLE_gte': int``
            - ``'avg7_COUNT_NEW_lte': int``
            - ``'avg7_COUNT_NEW_gte': int``
            - ``'avg7_COUNT_REFURBISHED_lte': int``
            - ``'avg7_COUNT_REFURBISHED_gte': int``
            - ``'avg7_COUNT_REVIEWS_lte': int``
            - ``'avg7_COUNT_REVIEWS_gte': int``
            - ``'avg7_COUNT_USED_lte': int``
            - ``'avg7_COUNT_USED_gte': int``
            - ``'avg7_EBAY_NEW_SHIPPING_lte': int``
            - ``'avg7_EBAY_NEW_SHIPPING_gte': int``
            - ``'avg7_EBAY_USED_SHIPPING_lte': int``
            - ``'avg7_EBAY_USED_SHIPPING_gte': int``
            - ``'avg7_LIGHTNING_DEAL_lte': int``
            - ``'avg7_LIGHTNING_DEAL_gte': int``
            - ``'avg7_LISTPRICE_lte': int``
            - ``'avg7_LISTPRICE_gte': int``
            - ``'avg7_NEW_lte': int``
            - ``'avg7_NEW_gte': int``
            - ``'avg7_NEW_FBA_lte': int``
            - ``'avg7_NEW_FBA_gte': int``
            - ``'avg7_NEW_FBM_SHIPPING_lte': int``
            - ``'avg7_NEW_FBM_SHIPPING_gte': int``
            - ``'avg7_RATING_lte': int``
            - ``'avg7_RATING_gte': int``
            - ``'avg7_REFURBISHED_lte': int``
            - ``'avg7_REFURBISHED_gte': int``
            - ``'avg7_REFURBISHED_SHIPPING_lte': int``
            - ``'avg7_REFURBISHED_SHIPPING_gte': int``
            - ``'avg7_RENT_lte': int``
            - ``'avg7_RENT_gte': int``
            - ``'avg7_SALES_lte': int``
            - ``'avg7_SALES_gte': int``
            - ``'avg7_TRADE_IN_lte': int``
            - ``'avg7_TRADE_IN_gte': int``
            - ``'avg7_USED_lte': int``
            - ``'avg7_USED_gte': int``
            - ``'avg7_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'avg7_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'avg7_USED_GOOD_SHIPPING_lte': int``
            - ``'avg7_USED_GOOD_SHIPPING_gte': int``
            - ``'avg7_USED_NEW_SHIPPING_lte': int``
            - ``'avg7_USED_NEW_SHIPPING_gte': int``
            - ``'avg7_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'avg7_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'avg7_WAREHOUSE_lte': int``
            - ``'avg7_WAREHOUSE_gte': int``
            - ``'avg90_AMAZON_lte': int``
            - ``'avg90_AMAZON_gte': int``
            - ``'avg90_BUY_BOX_SHIPPING_lte': int``
            - ``'avg90_BUY_BOX_SHIPPING_gte': int``
            - ``'avg90_COLLECTIBLE_lte': int``
            - ``'avg90_COLLECTIBLE_gte': int``
            - ``'avg90_COUNT_COLLECTIBLE_lte': int``
            - ``'avg90_COUNT_COLLECTIBLE_gte': int``
            - ``'avg90_COUNT_NEW_lte': int``
            - ``'avg90_COUNT_NEW_gte': int``
            - ``'avg90_COUNT_REFURBISHED_lte': int``
            - ``'avg90_COUNT_REFURBISHED_gte': int``
            - ``'avg90_COUNT_REVIEWS_lte': int``
            - ``'avg90_COUNT_REVIEWS_gte': int``
            - ``'avg90_COUNT_USED_lte': int``
            - ``'avg90_COUNT_USED_gte': int``
            - ``'avg90_EBAY_NEW_SHIPPING_lte': int``
            - ``'avg90_EBAY_NEW_SHIPPING_gte': int``
            - ``'avg90_EBAY_USED_SHIPPING_lte': int``
            - ``'avg90_EBAY_USED_SHIPPING_gte': int``
            - ``'avg90_LIGHTNING_DEAL_lte': int``
            - ``'avg90_LIGHTNING_DEAL_gte': int``
            - ``'avg90_LISTPRICE_lte': int``
            - ``'avg90_LISTPRICE_gte': int``
            - ``'avg90_NEW_lte': int``
            - ``'avg90_NEW_gte': int``
            - ``'avg90_NEW_FBA_lte': int``
            - ``'avg90_NEW_FBA_gte': int``
            - ``'avg90_NEW_FBM_SHIPPING_lte': int``
            - ``'avg90_NEW_FBM_SHIPPING_gte': int``
            - ``'avg90_RATING_lte': int``
            - ``'avg90_RATING_gte': int``
            - ``'avg90_REFURBISHED_lte': int``
            - ``'avg90_REFURBISHED_gte': int``
            - ``'avg90_REFURBISHED_SHIPPING_lte': int``
            - ``'avg90_REFURBISHED_SHIPPING_gte': int``
            - ``'avg90_RENT_lte': int``
            - ``'avg90_RENT_gte': int``
            - ``'avg90_SALES_lte': int``
            - ``'avg90_SALES_gte': int``
            - ``'avg90_TRADE_IN_lte': int``
            - ``'avg90_TRADE_IN_gte': int``
            - ``'avg90_USED_lte': int``
            - ``'avg90_USED_gte': int``
            - ``'avg90_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'avg90_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'avg90_USED_GOOD_SHIPPING_lte': int``
            - ``'avg90_USED_GOOD_SHIPPING_gte': int``
            - ``'avg90_USED_NEW_SHIPPING_lte': int``
            - ``'avg90_USED_NEW_SHIPPING_gte': int``
            - ``'avg90_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'avg90_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'avg90_WAREHOUSE_lte': int``
            - ``'avg90_WAREHOUSE_gte': int``
            - ``'backInStock_AMAZON': bool``
            - ``'backInStock_BUY_BOX_SHIPPING': bool``
            - ``'backInStock_COLLECTIBLE': bool``
            - ``'backInStock_COUNT_COLLECTIBLE': bool``
            - ``'backInStock_COUNT_NEW': bool``
            - ``'backInStock_COUNT_REFURBISHED': bool``
            - ``'backInStock_COUNT_REVIEWS': bool``
            - ``'backInStock_COUNT_USED': bool``
            - ``'backInStock_EBAY_NEW_SHIPPING': bool``
            - ``'backInStock_EBAY_USED_SHIPPING': bool``
            - ``'backInStock_LIGHTNING_DEAL': bool``
            - ``'backInStock_LISTPRICE': bool``
            - ``'backInStock_NEW': bool``
            - ``'backInStock_NEW_FBA': bool``
            - ``'backInStock_NEW_FBM_SHIPPING': bool``
            - ``'backInStock_RATING': bool``
            - ``'backInStock_REFURBISHED': bool``
            - ``'backInStock_REFURBISHED_SHIPPING': bool``
            - ``'backInStock_RENT': bool``
            - ``'backInStock_SALES': bool``
            - ``'backInStock_TRADE_IN': bool``
            - ``'backInStock_USED': bool``
            - ``'backInStock_USED_ACCEPTABLE_SHIPPING': bool``
            - ``'backInStock_USED_GOOD_SHIPPING': bool``
            - ``'backInStock_USED_NEW_SHIPPING': bool``
            - ``'backInStock_USED_VERY_GOOD_SHIPPING': bool``
            - ``'backInStock_WAREHOUSE': bool``
            - ``'binding': str``
            - ``'brand': str``
            - ``'buyBoxSellerId': str``
            - ``'color': str``
            - ``'couponOneTimeAbsolute_lte': int``
            - ``'couponOneTimeAbsolute_gte': int``
            - ``'couponOneTimePercent_lte': int``
            - ``'couponOneTimePercent_gte': int``
            - ``'couponSNSAbsolute_lte': int``
            - ``'couponSNSAbsolute_gte': int``
            - ``'couponSNSPercent_lte': int``
            - ``'couponSNSPercent_gte': int``
            - ``'current_AMAZON_lte': int``
            - ``'current_AMAZON_gte': int``
            - ``'current_BUY_BOX_SHIPPING_lte': int``
            - ``'current_BUY_BOX_SHIPPING_gte': int``
            - ``'current_COLLECTIBLE_lte': int``
            - ``'current_COLLECTIBLE_gte': int``
            - ``'current_COUNT_COLLECTIBLE_lte': int``
            - ``'current_COUNT_COLLECTIBLE_gte': int``
            - ``'current_COUNT_NEW_lte': int``
            - ``'current_COUNT_NEW_gte': int``
            - ``'current_COUNT_REFURBISHED_lte': int``
            - ``'current_COUNT_REFURBISHED_gte': int``
            - ``'current_COUNT_REVIEWS_lte': int``
            - ``'current_COUNT_REVIEWS_gte': int``
            - ``'current_COUNT_USED_lte': int``
            - ``'current_COUNT_USED_gte': int``
            - ``'current_EBAY_NEW_SHIPPING_lte': int``
            - ``'current_EBAY_NEW_SHIPPING_gte': int``
            - ``'current_EBAY_USED_SHIPPING_lte': int``
            - ``'current_EBAY_USED_SHIPPING_gte': int``
            - ``'current_LIGHTNING_DEAL_lte': int``
            - ``'current_LIGHTNING_DEAL_gte': int``
            - ``'current_LISTPRICE_lte': int``
            - ``'current_LISTPRICE_gte': int``
            - ``'current_NEW_lte': int``
            - ``'current_NEW_gte': int``
            - ``'current_NEW_FBA_lte': int``
            - ``'current_NEW_FBA_gte': int``
            - ``'current_NEW_FBM_SHIPPING_lte': int``
            - ``'current_NEW_FBM_SHIPPING_gte': int``
            - ``'current_RATING_lte': int``
            - ``'current_RATING_gte': int``
            - ``'current_REFURBISHED_lte': int``
            - ``'current_REFURBISHED_gte': int``
            - ``'current_REFURBISHED_SHIPPING_lte': int``
            - ``'current_REFURBISHED_SHIPPING_gte': int``
            - ``'current_RENT_lte': int``
            - ``'current_RENT_gte': int``
            - ``'current_SALES_lte': int``
            - ``'current_SALES_gte': int``
            - ``'current_TRADE_IN_lte': int``
            - ``'current_TRADE_IN_gte': int``
            - ``'current_USED_lte': int``
            - ``'current_USED_gte': int``
            - ``'current_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'current_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'current_USED_GOOD_SHIPPING_lte': int``
            - ``'current_USED_GOOD_SHIPPING_gte': int``
            - ``'current_USED_NEW_SHIPPING_lte': int``
            - ``'current_USED_NEW_SHIPPING_gte': int``
            - ``'current_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'current_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'current_WAREHOUSE_lte': int``
            - ``'current_WAREHOUSE_gte': int``
            - ``'delta1_AMAZON_lte': int``
            - ``'delta1_AMAZON_gte': int``
            - ``'delta1_BUY_BOX_SHIPPING_lte': int``
            - ``'delta1_BUY_BOX_SHIPPING_gte': int``
            - ``'delta1_COLLECTIBLE_lte': int``
            - ``'delta1_COLLECTIBLE_gte': int``
            - ``'delta1_COUNT_COLLECTIBLE_lte': int``
            - ``'delta1_COUNT_COLLECTIBLE_gte': int``
            - ``'delta1_COUNT_NEW_lte': int``
            - ``'delta1_COUNT_NEW_gte': int``
            - ``'delta1_COUNT_REFURBISHED_lte': int``
            - ``'delta1_COUNT_REFURBISHED_gte': int``
            - ``'delta1_COUNT_REVIEWS_lte': int``
            - ``'delta1_COUNT_REVIEWS_gte': int``
            - ``'delta1_COUNT_USED_lte': int``
            - ``'delta1_COUNT_USED_gte': int``
            - ``'delta1_EBAY_NEW_SHIPPING_lte': int``
            - ``'delta1_EBAY_NEW_SHIPPING_gte': int``
            - ``'delta1_EBAY_USED_SHIPPING_lte': int``
            - ``'delta1_EBAY_USED_SHIPPING_gte': int``
            - ``'delta1_LIGHTNING_DEAL_lte': int``
            - ``'delta1_LIGHTNING_DEAL_gte': int``
            - ``'delta1_LISTPRICE_lte': int``
            - ``'delta1_LISTPRICE_gte': int``
            - ``'delta1_NEW_lte': int``
            - ``'delta1_NEW_gte': int``
            - ``'delta1_NEW_FBA_lte': int``
            - ``'delta1_NEW_FBA_gte': int``
            - ``'delta1_NEW_FBM_SHIPPING_lte': int``
            - ``'delta1_NEW_FBM_SHIPPING_gte': int``
            - ``'delta1_RATING_lte': int``
            - ``'delta1_RATING_gte': int``
            - ``'delta1_REFURBISHED_lte': int``
            - ``'delta1_REFURBISHED_gte': int``
            - ``'delta1_REFURBISHED_SHIPPING_lte': int``
            - ``'delta1_REFURBISHED_SHIPPING_gte': int``
            - ``'delta1_RENT_lte': int``
            - ``'delta1_RENT_gte': int``
            - ``'delta1_SALES_lte': int``
            - ``'delta1_SALES_gte': int``
            - ``'delta1_TRADE_IN_lte': int``
            - ``'delta1_TRADE_IN_gte': int``
            - ``'delta1_USED_lte': int``
            - ``'delta1_USED_gte': int``
            - ``'delta1_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'delta1_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'delta1_USED_GOOD_SHIPPING_lte': int``
            - ``'delta1_USED_GOOD_SHIPPING_gte': int``
            - ``'delta1_USED_NEW_SHIPPING_lte': int``
            - ``'delta1_USED_NEW_SHIPPING_gte': int``
            - ``'delta1_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'delta1_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'delta1_WAREHOUSE_lte': int``
            - ``'delta1_WAREHOUSE_gte': int``
            - ``'delta30_AMAZON_lte': int``
            - ``'delta30_AMAZON_gte': int``
            - ``'delta30_BUY_BOX_SHIPPING_lte': int``
            - ``'delta30_BUY_BOX_SHIPPING_gte': int``
            - ``'delta30_COLLECTIBLE_lte': int``
            - ``'delta30_COLLECTIBLE_gte': int``
            - ``'delta30_COUNT_COLLECTIBLE_lte': int``
            - ``'delta30_COUNT_COLLECTIBLE_gte': int``
            - ``'delta30_COUNT_NEW_lte': int``
            - ``'delta30_COUNT_NEW_gte': int``
            - ``'delta30_COUNT_REFURBISHED_lte': int``
            - ``'delta30_COUNT_REFURBISHED_gte': int``
            - ``'delta30_COUNT_REVIEWS_lte': int``
            - ``'delta30_COUNT_REVIEWS_gte': int``
            - ``'delta30_COUNT_USED_lte': int``
            - ``'delta30_COUNT_USED_gte': int``
            - ``'delta30_EBAY_NEW_SHIPPING_lte': int``
            - ``'delta30_EBAY_NEW_SHIPPING_gte': int``
            - ``'delta30_EBAY_USED_SHIPPING_lte': int``
            - ``'delta30_EBAY_USED_SHIPPING_gte': int``
            - ``'delta30_LIGHTNING_DEAL_lte': int``
            - ``'delta30_LIGHTNING_DEAL_gte': int``
            - ``'delta30_LISTPRICE_lte': int``
            - ``'delta30_LISTPRICE_gte': int``
            - ``'delta30_NEW_lte': int``
            - ``'delta30_NEW_gte': int``
            - ``'delta30_NEW_FBA_lte': int``
            - ``'delta30_NEW_FBA_gte': int``
            - ``'delta30_NEW_FBM_SHIPPING_lte': int``
            - ``'delta30_NEW_FBM_SHIPPING_gte': int``
            - ``'delta30_RATING_lte': int``
            - ``'delta30_RATING_gte': int``
            - ``'delta30_REFURBISHED_lte': int``
            - ``'delta30_REFURBISHED_gte': int``
            - ``'delta30_REFURBISHED_SHIPPING_lte': int``
            - ``'delta30_REFURBISHED_SHIPPING_gte': int``
            - ``'delta30_RENT_lte': int``
            - ``'delta30_RENT_gte': int``
            - ``'delta30_SALES_lte': int``
            - ``'delta30_SALES_gte': int``
            - ``'delta30_TRADE_IN_lte': int``
            - ``'delta30_TRADE_IN_gte': int``
            - ``'delta30_USED_lte': int``
            - ``'delta30_USED_gte': int``
            - ``'delta30_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'delta30_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'delta30_USED_GOOD_SHIPPING_lte': int``
            - ``'delta30_USED_GOOD_SHIPPING_gte': int``
            - ``'delta30_USED_NEW_SHIPPING_lte': int``
            - ``'delta30_USED_NEW_SHIPPING_gte': int``
            - ``'delta30_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'delta30_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'delta30_WAREHOUSE_lte': int``
            - ``'delta30_WAREHOUSE_gte': int``
            - ``'delta7_AMAZON_lte': int``
            - ``'delta7_AMAZON_gte': int``
            - ``'delta7_BUY_BOX_SHIPPING_lte': int``
            - ``'delta7_BUY_BOX_SHIPPING_gte': int``
            - ``'delta7_COLLECTIBLE_lte': int``
            - ``'delta7_COLLECTIBLE_gte': int``
            - ``'delta7_COUNT_COLLECTIBLE_lte': int``
            - ``'delta7_COUNT_COLLECTIBLE_gte': int``
            - ``'delta7_COUNT_NEW_lte': int``
            - ``'delta7_COUNT_NEW_gte': int``
            - ``'delta7_COUNT_REFURBISHED_lte': int``
            - ``'delta7_COUNT_REFURBISHED_gte': int``
            - ``'delta7_COUNT_REVIEWS_lte': int``
            - ``'delta7_COUNT_REVIEWS_gte': int``
            - ``'delta7_COUNT_USED_lte': int``
            - ``'delta7_COUNT_USED_gte': int``
            - ``'delta7_EBAY_NEW_SHIPPING_lte': int``
            - ``'delta7_EBAY_NEW_SHIPPING_gte': int``
            - ``'delta7_EBAY_USED_SHIPPING_lte': int``
            - ``'delta7_EBAY_USED_SHIPPING_gte': int``
            - ``'delta7_LIGHTNING_DEAL_lte': int``
            - ``'delta7_LIGHTNING_DEAL_gte': int``
            - ``'delta7_LISTPRICE_lte': int``
            - ``'delta7_LISTPRICE_gte': int``
            - ``'delta7_NEW_lte': int``
            - ``'delta7_NEW_gte': int``
            - ``'delta7_NEW_FBA_lte': int``
            - ``'delta7_NEW_FBA_gte': int``
            - ``'delta7_NEW_FBM_SHIPPING_lte': int``
            - ``'delta7_NEW_FBM_SHIPPING_gte': int``
            - ``'delta7_RATING_lte': int``
            - ``'delta7_RATING_gte': int``
            - ``'delta7_REFURBISHED_lte': int``
            - ``'delta7_REFURBISHED_gte': int``
            - ``'delta7_REFURBISHED_SHIPPING_lte': int``
            - ``'delta7_REFURBISHED_SHIPPING_gte': int``
            - ``'delta7_RENT_lte': int``
            - ``'delta7_RENT_gte': int``
            - ``'delta7_SALES_lte': int``
            - ``'delta7_SALES_gte': int``
            - ``'delta7_TRADE_IN_lte': int``
            - ``'delta7_TRADE_IN_gte': int``
            - ``'delta7_USED_lte': int``
            - ``'delta7_USED_gte': int``
            - ``'delta7_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'delta7_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'delta7_USED_GOOD_SHIPPING_lte': int``
            - ``'delta7_USED_GOOD_SHIPPING_gte': int``
            - ``'delta7_USED_NEW_SHIPPING_lte': int``
            - ``'delta7_USED_NEW_SHIPPING_gte': int``
            - ``'delta7_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'delta7_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'delta7_WAREHOUSE_lte': int``
            - ``'delta7_WAREHOUSE_gte': int``
            - ``'delta90_AMAZON_lte': int``
            - ``'delta90_AMAZON_gte': int``
            - ``'delta90_BUY_BOX_SHIPPING_lte': int``
            - ``'delta90_BUY_BOX_SHIPPING_gte': int``
            - ``'delta90_COLLECTIBLE_lte': int``
            - ``'delta90_COLLECTIBLE_gte': int``
            - ``'delta90_COUNT_COLLECTIBLE_lte': int``
            - ``'delta90_COUNT_COLLECTIBLE_gte': int``
            - ``'delta90_COUNT_NEW_lte': int``
            - ``'delta90_COUNT_NEW_gte': int``
            - ``'delta90_COUNT_REFURBISHED_lte': int``
            - ``'delta90_COUNT_REFURBISHED_gte': int``
            - ``'delta90_COUNT_REVIEWS_lte': int``
            - ``'delta90_COUNT_REVIEWS_gte': int``
            - ``'delta90_COUNT_USED_lte': int``
            - ``'delta90_COUNT_USED_gte': int``
            - ``'delta90_EBAY_NEW_SHIPPING_lte': int``
            - ``'delta90_EBAY_NEW_SHIPPING_gte': int``
            - ``'delta90_EBAY_USED_SHIPPING_lte': int``
            - ``'delta90_EBAY_USED_SHIPPING_gte': int``
            - ``'delta90_LIGHTNING_DEAL_lte': int``
            - ``'delta90_LIGHTNING_DEAL_gte': int``
            - ``'delta90_LISTPRICE_lte': int``
            - ``'delta90_LISTPRICE_gte': int``
            - ``'delta90_NEW_lte': int``
            - ``'delta90_NEW_gte': int``
            - ``'delta90_NEW_FBA_lte': int``
            - ``'delta90_NEW_FBA_gte': int``
            - ``'delta90_NEW_FBM_SHIPPING_lte': int``
            - ``'delta90_NEW_FBM_SHIPPING_gte': int``
            - ``'delta90_RATING_lte': int``
            - ``'delta90_RATING_gte': int``
            - ``'delta90_REFURBISHED_lte': int``
            - ``'delta90_REFURBISHED_gte': int``
            - ``'delta90_REFURBISHED_SHIPPING_lte': int``
            - ``'delta90_REFURBISHED_SHIPPING_gte': int``
            - ``'delta90_RENT_lte': int``
            - ``'delta90_RENT_gte': int``
            - ``'delta90_SALES_lte': int``
            - ``'delta90_SALES_gte': int``
            - ``'delta90_TRADE_IN_lte': int``
            - ``'delta90_TRADE_IN_gte': int``
            - ``'delta90_USED_lte': int``
            - ``'delta90_USED_gte': int``
            - ``'delta90_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'delta90_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'delta90_USED_GOOD_SHIPPING_lte': int``
            - ``'delta90_USED_GOOD_SHIPPING_gte': int``
            - ``'delta90_USED_NEW_SHIPPING_lte': int``
            - ``'delta90_USED_NEW_SHIPPING_gte': int``
            - ``'delta90_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'delta90_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'delta90_WAREHOUSE_lte': int``
            - ``'delta90_WAREHOUSE_gte': int``
            - ``'deltaLast_AMAZON_lte': int``
            - ``'deltaLast_AMAZON_gte': int``
            - ``'deltaLast_BUY_BOX_SHIPPING_lte': int``
            - ``'deltaLast_BUY_BOX_SHIPPING_gte': int``
            - ``'deltaLast_COLLECTIBLE_lte': int``
            - ``'deltaLast_COLLECTIBLE_gte': int``
            - ``'deltaLast_COUNT_COLLECTIBLE_lte': int``
            - ``'deltaLast_COUNT_COLLECTIBLE_gte': int``
            - ``'deltaLast_COUNT_NEW_lte': int``
            - ``'deltaLast_COUNT_NEW_gte': int``
            - ``'deltaLast_COUNT_REFURBISHED_lte': int``
            - ``'deltaLast_COUNT_REFURBISHED_gte': int``
            - ``'deltaLast_COUNT_REVIEWS_lte': int``
            - ``'deltaLast_COUNT_REVIEWS_gte': int``
            - ``'deltaLast_COUNT_USED_lte': int``
            - ``'deltaLast_COUNT_USED_gte': int``
            - ``'deltaLast_EBAY_NEW_SHIPPING_lte': int``
            - ``'deltaLast_EBAY_NEW_SHIPPING_gte': int``
            - ``'deltaLast_EBAY_USED_SHIPPING_lte': int``
            - ``'deltaLast_EBAY_USED_SHIPPING_gte': int``
            - ``'deltaLast_LIGHTNING_DEAL_lte': int``
            - ``'deltaLast_LIGHTNING_DEAL_gte': int``
            - ``'deltaLast_LISTPRICE_lte': int``
            - ``'deltaLast_LISTPRICE_gte': int``
            - ``'deltaLast_NEW_lte': int``
            - ``'deltaLast_NEW_gte': int``
            - ``'deltaLast_NEW_FBA_lte': int``
            - ``'deltaLast_NEW_FBA_gte': int``
            - ``'deltaLast_NEW_FBM_SHIPPING_lte': int``
            - ``'deltaLast_NEW_FBM_SHIPPING_gte': int``
            - ``'deltaLast_RATING_lte': int``
            - ``'deltaLast_RATING_gte': int``
            - ``'deltaLast_REFURBISHED_lte': int``
            - ``'deltaLast_REFURBISHED_gte': int``
            - ``'deltaLast_REFURBISHED_SHIPPING_lte': int``
            - ``'deltaLast_REFURBISHED_SHIPPING_gte': int``
            - ``'deltaLast_RENT_lte': int``
            - ``'deltaLast_RENT_gte': int``
            - ``'deltaLast_SALES_lte': int``
            - ``'deltaLast_SALES_gte': int``
            - ``'deltaLast_TRADE_IN_lte': int``
            - ``'deltaLast_TRADE_IN_gte': int``
            - ``'deltaLast_USED_lte': int``
            - ``'deltaLast_USED_gte': int``
            - ``'deltaLast_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'deltaLast_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'deltaLast_USED_GOOD_SHIPPING_lte': int``
            - ``'deltaLast_USED_GOOD_SHIPPING_gte': int``
            - ``'deltaLast_USED_NEW_SHIPPING_lte': int``
            - ``'deltaLast_USED_NEW_SHIPPING_gte': int``
            - ``'deltaLast_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'deltaLast_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'deltaLast_WAREHOUSE_lte': int``
            - ``'deltaLast_WAREHOUSE_gte': int``
            - ``'deltaPercent1_AMAZON_lte': int``
            - ``'deltaPercent1_AMAZON_gte': int``
            - ``'deltaPercent1_BUY_BOX_SHIPPING_lte': int``
            - ``'deltaPercent1_BUY_BOX_SHIPPING_gte': int``
            - ``'deltaPercent1_COLLECTIBLE_lte': int``
            - ``'deltaPercent1_COLLECTIBLE_gte': int``
            - ``'deltaPercent1_COUNT_COLLECTIBLE_lte': int``
            - ``'deltaPercent1_COUNT_COLLECTIBLE_gte': int``
            - ``'deltaPercent1_COUNT_NEW_lte': int``
            - ``'deltaPercent1_COUNT_NEW_gte': int``
            - ``'deltaPercent1_COUNT_REFURBISHED_lte': int``
            - ``'deltaPercent1_COUNT_REFURBISHED_gte': int``
            - ``'deltaPercent1_COUNT_REVIEWS_lte': int``
            - ``'deltaPercent1_COUNT_REVIEWS_gte': int``
            - ``'deltaPercent1_COUNT_USED_lte': int``
            - ``'deltaPercent1_COUNT_USED_gte': int``
            - ``'deltaPercent1_EBAY_NEW_SHIPPING_lte': int``
            - ``'deltaPercent1_EBAY_NEW_SHIPPING_gte': int``
            - ``'deltaPercent1_EBAY_USED_SHIPPING_lte': int``
            - ``'deltaPercent1_EBAY_USED_SHIPPING_gte': int``
            - ``'deltaPercent1_LIGHTNING_DEAL_lte': int``
            - ``'deltaPercent1_LIGHTNING_DEAL_gte': int``
            - ``'deltaPercent1_LISTPRICE_lte': int``
            - ``'deltaPercent1_LISTPRICE_gte': int``
            - ``'deltaPercent1_NEW_lte': int``
            - ``'deltaPercent1_NEW_gte': int``
            - ``'deltaPercent1_NEW_FBA_lte': int``
            - ``'deltaPercent1_NEW_FBA_gte': int``
            - ``'deltaPercent1_NEW_FBM_SHIPPING_lte': int``
            - ``'deltaPercent1_NEW_FBM_SHIPPING_gte': int``
            - ``'deltaPercent1_RATING_lte': int``
            - ``'deltaPercent1_RATING_gte': int``
            - ``'deltaPercent1_REFURBISHED_lte': int``
            - ``'deltaPercent1_REFURBISHED_gte': int``
            - ``'deltaPercent1_REFURBISHED_SHIPPING_lte': int``
            - ``'deltaPercent1_REFURBISHED_SHIPPING_gte': int``
            - ``'deltaPercent1_RENT_lte': int``
            - ``'deltaPercent1_RENT_gte': int``
            - ``'deltaPercent1_SALES_lte': int``
            - ``'deltaPercent1_SALES_gte': int``
            - ``'deltaPercent1_TRADE_IN_lte': int``
            - ``'deltaPercent1_TRADE_IN_gte': int``
            - ``'deltaPercent1_USED_lte': int``
            - ``'deltaPercent1_USED_gte': int``
            - ``'deltaPercent1_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'deltaPercent1_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'deltaPercent1_USED_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent1_USED_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent1_USED_NEW_SHIPPING_lte': int``
            - ``'deltaPercent1_USED_NEW_SHIPPING_gte': int``
            - ``'deltaPercent1_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent1_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent1_WAREHOUSE_lte': int``
            - ``'deltaPercent1_WAREHOUSE_gte': int``
            - ``'deltaPercent30_AMAZON_lte': int``
            - ``'deltaPercent30_AMAZON_gte': int``
            - ``'deltaPercent30_BUY_BOX_SHIPPING_lte': int``
            - ``'deltaPercent30_BUY_BOX_SHIPPING_gte': int``
            - ``'deltaPercent30_COLLECTIBLE_lte': int``
            - ``'deltaPercent30_COLLECTIBLE_gte': int``
            - ``'deltaPercent30_COUNT_COLLECTIBLE_lte': int``
            - ``'deltaPercent30_COUNT_COLLECTIBLE_gte': int``
            - ``'deltaPercent30_COUNT_NEW_lte': int``
            - ``'deltaPercent30_COUNT_NEW_gte': int``
            - ``'deltaPercent30_COUNT_REFURBISHED_lte': int``
            - ``'deltaPercent30_COUNT_REFURBISHED_gte': int``
            - ``'deltaPercent30_COUNT_REVIEWS_lte': int``
            - ``'deltaPercent30_COUNT_REVIEWS_gte': int``
            - ``'deltaPercent30_COUNT_USED_lte': int``
            - ``'deltaPercent30_COUNT_USED_gte': int``
            - ``'deltaPercent30_EBAY_NEW_SHIPPING_lte': int``
            - ``'deltaPercent30_EBAY_NEW_SHIPPING_gte': int``
            - ``'deltaPercent30_EBAY_USED_SHIPPING_lte': int``
            - ``'deltaPercent30_EBAY_USED_SHIPPING_gte': int``
            - ``'deltaPercent30_LIGHTNING_DEAL_lte': int``
            - ``'deltaPercent30_LIGHTNING_DEAL_gte': int``
            - ``'deltaPercent30_LISTPRICE_lte': int``
            - ``'deltaPercent30_LISTPRICE_gte': int``
            - ``'deltaPercent30_NEW_lte': int``
            - ``'deltaPercent30_NEW_gte': int``
            - ``'deltaPercent30_NEW_FBA_lte': int``
            - ``'deltaPercent30_NEW_FBA_gte': int``
            - ``'deltaPercent30_NEW_FBM_SHIPPING_lte': int``
            - ``'deltaPercent30_NEW_FBM_SHIPPING_gte': int``
            - ``'deltaPercent30_RATING_lte': int``
            - ``'deltaPercent30_RATING_gte': int``
            - ``'deltaPercent30_REFURBISHED_lte': int``
            - ``'deltaPercent30_REFURBISHED_gte': int``
            - ``'deltaPercent30_REFURBISHED_SHIPPING_lte': int``
            - ``'deltaPercent30_REFURBISHED_SHIPPING_gte': int``
            - ``'deltaPercent30_RENT_lte': int``
            - ``'deltaPercent30_RENT_gte': int``
            - ``'deltaPercent30_SALES_lte': int``
            - ``'deltaPercent30_SALES_gte': int``
            - ``'deltaPercent30_TRADE_IN_lte': int``
            - ``'deltaPercent30_TRADE_IN_gte': int``
            - ``'deltaPercent30_USED_lte': int``
            - ``'deltaPercent30_USED_gte': int``
            - ``'deltaPercent30_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'deltaPercent30_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'deltaPercent30_USED_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent30_USED_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent30_USED_NEW_SHIPPING_lte': int``
            - ``'deltaPercent30_USED_NEW_SHIPPING_gte': int``
            - ``'deltaPercent30_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent30_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent30_WAREHOUSE_lte': int``
            - ``'deltaPercent30_WAREHOUSE_gte': int``
            - ``'deltaPercent7_AMAZON_lte': int``
            - ``'deltaPercent7_AMAZON_gte': int``
            - ``'deltaPercent7_BUY_BOX_SHIPPING_lte': int``
            - ``'deltaPercent7_BUY_BOX_SHIPPING_gte': int``
            - ``'deltaPercent7_COLLECTIBLE_lte': int``
            - ``'deltaPercent7_COLLECTIBLE_gte': int``
            - ``'deltaPercent7_COUNT_COLLECTIBLE_lte': int``
            - ``'deltaPercent7_COUNT_COLLECTIBLE_gte': int``
            - ``'deltaPercent7_COUNT_NEW_lte': int``
            - ``'deltaPercent7_COUNT_NEW_gte': int``
            - ``'deltaPercent7_COUNT_REFURBISHED_lte': int``
            - ``'deltaPercent7_COUNT_REFURBISHED_gte': int``
            - ``'deltaPercent7_COUNT_REVIEWS_lte': int``
            - ``'deltaPercent7_COUNT_REVIEWS_gte': int``
            - ``'deltaPercent7_COUNT_USED_lte': int``
            - ``'deltaPercent7_COUNT_USED_gte': int``
            - ``'deltaPercent7_EBAY_NEW_SHIPPING_lte': int``
            - ``'deltaPercent7_EBAY_NEW_SHIPPING_gte': int``
            - ``'deltaPercent7_EBAY_USED_SHIPPING_lte': int``
            - ``'deltaPercent7_EBAY_USED_SHIPPING_gte': int``
            - ``'deltaPercent7_LIGHTNING_DEAL_lte': int``
            - ``'deltaPercent7_LIGHTNING_DEAL_gte': int``
            - ``'deltaPercent7_LISTPRICE_lte': int``
            - ``'deltaPercent7_LISTPRICE_gte': int``
            - ``'deltaPercent7_NEW_lte': int``
            - ``'deltaPercent7_NEW_gte': int``
            - ``'deltaPercent7_NEW_FBA_lte': int``
            - ``'deltaPercent7_NEW_FBA_gte': int``
            - ``'deltaPercent7_NEW_FBM_SHIPPING_lte': int``
            - ``'deltaPercent7_NEW_FBM_SHIPPING_gte': int``
            - ``'deltaPercent7_RATING_lte': int``
            - ``'deltaPercent7_RATING_gte': int``
            - ``'deltaPercent7_REFURBISHED_lte': int``
            - ``'deltaPercent7_REFURBISHED_gte': int``
            - ``'deltaPercent7_REFURBISHED_SHIPPING_lte': int``
            - ``'deltaPercent7_REFURBISHED_SHIPPING_gte': int``
            - ``'deltaPercent7_RENT_lte': int``
            - ``'deltaPercent7_RENT_gte': int``
            - ``'deltaPercent7_SALES_lte': int``
            - ``'deltaPercent7_SALES_gte': int``
            - ``'deltaPercent7_TRADE_IN_lte': int``
            - ``'deltaPercent7_TRADE_IN_gte': int``
            - ``'deltaPercent7_USED_lte': int``
            - ``'deltaPercent7_USED_gte': int``
            - ``'deltaPercent7_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'deltaPercent7_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'deltaPercent7_USED_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent7_USED_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent7_USED_NEW_SHIPPING_lte': int``
            - ``'deltaPercent7_USED_NEW_SHIPPING_gte': int``
            - ``'deltaPercent7_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent7_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent7_WAREHOUSE_lte': int``
            - ``'deltaPercent7_WAREHOUSE_gte': int``
            - ``'deltaPercent90_AMAZON_lte': int``
            - ``'deltaPercent90_AMAZON_gte': int``
            - ``'deltaPercent90_BUY_BOX_SHIPPING_lte': int``
            - ``'deltaPercent90_BUY_BOX_SHIPPING_gte': int``
            - ``'deltaPercent90_COLLECTIBLE_lte': int``
            - ``'deltaPercent90_COLLECTIBLE_gte': int``
            - ``'deltaPercent90_COUNT_COLLECTIBLE_lte': int``
            - ``'deltaPercent90_COUNT_COLLECTIBLE_gte': int``
            - ``'deltaPercent90_COUNT_NEW_lte': int``
            - ``'deltaPercent90_COUNT_NEW_gte': int``
            - ``'deltaPercent90_COUNT_REFURBISHED_lte': int``
            - ``'deltaPercent90_COUNT_REFURBISHED_gte': int``
            - ``'deltaPercent90_COUNT_REVIEWS_lte': int``
            - ``'deltaPercent90_COUNT_REVIEWS_gte': int``
            - ``'deltaPercent90_COUNT_USED_lte': int``
            - ``'deltaPercent90_COUNT_USED_gte': int``
            - ``'deltaPercent90_EBAY_NEW_SHIPPING_lte': int``
            - ``'deltaPercent90_EBAY_NEW_SHIPPING_gte': int``
            - ``'deltaPercent90_EBAY_USED_SHIPPING_lte': int``
            - ``'deltaPercent90_EBAY_USED_SHIPPING_gte': int``
            - ``'deltaPercent90_LIGHTNING_DEAL_lte': int``
            - ``'deltaPercent90_LIGHTNING_DEAL_gte': int``
            - ``'deltaPercent90_LISTPRICE_lte': int``
            - ``'deltaPercent90_LISTPRICE_gte': int``
            - ``'deltaPercent90_NEW_lte': int``
            - ``'deltaPercent90_NEW_gte': int``
            - ``'deltaPercent90_NEW_FBA_lte': int``
            - ``'deltaPercent90_NEW_FBA_gte': int``
            - ``'deltaPercent90_NEW_FBM_SHIPPING_lte': int``
            - ``'deltaPercent90_NEW_FBM_SHIPPING_gte': int``
            - ``'deltaPercent90_RATING_lte': int``
            - ``'deltaPercent90_RATING_gte': int``
            - ``'deltaPercent90_REFURBISHED_lte': int``
            - ``'deltaPercent90_REFURBISHED_gte': int``
            - ``'deltaPercent90_REFURBISHED_SHIPPING_lte': int``
            - ``'deltaPercent90_REFURBISHED_SHIPPING_gte': int``
            - ``'deltaPercent90_RENT_lte': int``
            - ``'deltaPercent90_RENT_gte': int``
            - ``'deltaPercent90_SALES_lte': int``
            - ``'deltaPercent90_SALES_gte': int``
            - ``'deltaPercent90_TRADE_IN_lte': int``
            - ``'deltaPercent90_TRADE_IN_gte': int``
            - ``'deltaPercent90_USED_lte': int``
            - ``'deltaPercent90_USED_gte': int``
            - ``'deltaPercent90_USED_ACCEPTABLE_SHIPPING_lte': int``
            - ``'deltaPercent90_USED_ACCEPTABLE_SHIPPING_gte': int``
            - ``'deltaPercent90_USED_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent90_USED_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent90_USED_NEW_SHIPPING_lte': int``
            - ``'deltaPercent90_USED_NEW_SHIPPING_gte': int``
            - ``'deltaPercent90_USED_VERY_GOOD_SHIPPING_lte': int``
            - ``'deltaPercent90_USED_VERY_GOOD_SHIPPING_gte': int``
            - ``'deltaPercent90_WAREHOUSE_lte': int``
            - ``'deltaPercent90_WAREHOUSE_gte': int``
            - ``'department': str``
            - ``'edition': str``
            - ``'fbaFees_lte': int``
            - ``'fbaFees_gte': int``
            - ``'format': str``
            - ``'genre': str``
            - ``'hasParentASIN': bool``
            - ``'hasReviews': bool``
            - ``'hazardousMaterialType_lte': int``
            - ``'hazardousMaterialType_gte': int``
            - ``'isAdultProduct': bool``
            - ``'isEligibleForSuperSaverShipping': bool``
            - ``'isEligibleForTradeIn': bool``
            - ``'isHighestOffer': bool``
            - ``'isHighest_AMAZON': bool``
            - ``'isHighest_BUY_BOX_SHIPPING': bool``
            - ``'isHighest_COLLECTIBLE': bool``
            - ``'isHighest_COUNT_COLLECTIBLE': bool``
            - ``'isHighest_COUNT_NEW': bool``
            - ``'isHighest_COUNT_REFURBISHED': bool``
            - ``'isHighest_COUNT_REVIEWS': bool``
            - ``'isHighest_COUNT_USED': bool``
            - ``'isHighest_EBAY_NEW_SHIPPING': bool``
            - ``'isHighest_EBAY_USED_SHIPPING': bool``
            - ``'isHighest_LIGHTNING_DEAL': bool``
            - ``'isHighest_LISTPRICE': bool``
            - ``'isHighest_NEW': bool``
            - ``'isHighest_NEW_FBA': bool``
            - ``'isHighest_NEW_FBM_SHIPPING': bool``
            - ``'isHighest_RATING': bool``
            - ``'isHighest_REFURBISHED': bool``
            - ``'isHighest_REFURBISHED_SHIPPING': bool``
            - ``'isHighest_RENT': bool``
            - ``'isHighest_SALES': bool``
            - ``'isHighest_TRADE_IN': bool``
            - ``'isHighest_USED': bool``
            - ``'isHighest_USED_ACCEPTABLE_SHIPPING': bool``
            - ``'isHighest_USED_GOOD_SHIPPING': bool``
            - ``'isHighest_USED_NEW_SHIPPING': bool``
            - ``'isHighest_USED_VERY_GOOD_SHIPPING': bool``
            - ``'isHighest_WAREHOUSE': bool``
            - ``'isLowestOffer': bool``
            - ``'isLowest_AMAZON': bool``
            - ``'isLowest_BUY_BOX_SHIPPING': bool``
            - ``'isLowest_COLLECTIBLE': bool``
            - ``'isLowest_COUNT_COLLECTIBLE': bool``
            - ``'isLowest_COUNT_NEW': bool``
            - ``'isLowest_COUNT_REFURBISHED': bool``
            - ``'isLowest_COUNT_REVIEWS': bool``
            - ``'isLowest_COUNT_USED': bool``
            - ``'isLowest_EBAY_NEW_SHIPPING': bool``
            - ``'isLowest_EBAY_USED_SHIPPING': bool``
            - ``'isLowest_LIGHTNING_DEAL': bool``
            - ``'isLowest_LISTPRICE': bool``
            - ``'isLowest_NEW': bool``
            - ``'isLowest_NEW_FBA': bool``
            - ``'isLowest_NEW_FBM_SHIPPING': bool``
            - ``'isLowest_RATING': bool``
            - ``'isLowest_REFURBISHED': bool``
            - ``'isLowest_REFURBISHED_SHIPPING': bool``
            - ``'isLowest_RENT': bool``
            - ``'isLowest_SALES': bool``
            - ``'isLowest_TRADE_IN': bool``
            - ``'isLowest_USED': bool``
            - ``'isLowest_USED_ACCEPTABLE_SHIPPING': bool``
            - ``'isLowest_USED_GOOD_SHIPPING': bool``
            - ``'isLowest_USED_NEW_SHIPPING': bool``
            - ``'isLowest_USED_VERY_GOOD_SHIPPING': bool``
            - ``'isLowest_WAREHOUSE': bool``
            - ``'isPrimeExclusive': bool``
            - ``'isSNS': bool``
            - ``'label': str``
            - ``'languages': str``
            - ``'lastOffersUpdate_lte': int``
            - ``'lastOffersUpdate_gte': int``
            - ``'lastPriceChange_lte': int``
            - ``'lastPriceChange_gte': int``
            - ``'lastRatingUpdate_lte': int``
            - ``'lastRatingUpdate_gte': int``
            - ``'lastUpdate_lte': int``
            - ``'lastUpdate_gte': int``
            - ``'lightningEnd_lte': int``
            - ``'lightningEnd_gte': int``
            - ``'lightningStart_lte': int``
            - ``'lightningStart_gte': int``
            - ``'listedSince_lte': int``
            - ``'listedSince_gte': int``
            - ``'manufacturer': str``
            - ``'model': str``
            - ``'newPriceIsMAP': bool``
            - ``'nextUpdate_lte': int``
            - ``'nextUpdate_gte': int``
            - ``'numberOfItems_lte': int``
            - ``'numberOfItems_gte': int``
            - ``'numberOfPages_lte': int``
            - ``'numberOfPages_gte': int``
            - ``'numberOfTrackings_lte': int``
            - ``'numberOfTrackings_gte': int``
            - ``'offerCountFBA_lte': int``
            - ``'offerCountFBA_gte': int``
            - ``'offerCountFBM_lte': int``
            - ``'offerCountFBM_gte': int``
            - ``'outOfStockPercentageInInterval_lte': int``
            - ``'outOfStockPercentageInInterval_gte': int``
            - ``'packageDimension_lte': int``
            - ``'packageDimension_gte': int``
            - ``'packageHeight_lte': int``
            - ``'packageHeight_gte': int``
            - ``'packageLength_lte': int``
            - ``'packageLength_gte': int``
            - ``'packageQuantity_lte': int``
            - ``'packageQuantity_gte': int``
            - ``'packageWeight_lte': int``
            - ``'packageWeight_gte': int``
            - ``'packageWidth_lte': int``
            - ``'packageWidth_gte': int``
            - ``'partNumber': str``
            - ``'platform': str``
            - ``'productGroup': str``
            - ``'productType': int``
            - ``'promotions': int``
            - ``'publicationDate_lte': int``
            - ``'publicationDate_gte': int``
            - ``'publisher': str``
            - ``'releaseDate_lte': int``
            - ``'releaseDate_gte': int``
            - ``'rootCategory': int``
            - ``'sellerIds': str``
            - ``'sellerIdsLowestFBA': str``
            - ``'sellerIdsLowestFBM': str``
            - ``'size': str``
            - ``'salesRankDrops180_lte': int``
            - ``'salesRankDrops180_gte': int``
            - ``'salesRankDrops90_lte': int``
            - ``'salesRankDrops90_gte': int``
            - ``'salesRankDrops30_lte': int``
            - ``'salesRankDrops30_gte': int``
            - ``'stockAmazon_lte': int``
            - ``'stockAmazon_gte': int``
            - ``'stockBuyBox_lte': int``
            - ``'stockBuyBox_gte': int``
            - ``'studio': str``
            - ``'title': str``
            - ``'title_flag': str``
            - ``'trackingSince_lte': int``
            - ``'trackingSince_gte': int``
            - ``'type': str``
            - ``'mpn': str``
            - ``'outOfStockPercentage90_lte': int``
            - ``'outOfStockPercentage90_gte': int``
            - ``'categories_include': int``
            - ``'categories_exclude': int``

        domain : str, optional
            One of the following Amazon domains: RESERVED, US, GB, DE,
            FR, JP, CA, CN, IT, ES, IN, MX Defaults to US.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Examples
        --------
        Query for all of Jim Butcher's books

        >>> import keepa
        >>> api = keepa.AsyncKeepa('ENTER_ACTUAL_KEY_HERE')
        >>> product_parms = {'author': 'jim butcher'}
        >>> products = await api.product_finder(product_parms)
        """
        # verify valid keys
        for key in product_parms:
            if key not in PRODUCT_REQUEST_KEYS:
                raise RuntimeError('Invalid key "%s"' % key)

            # verify json type
            key_type = PRODUCT_REQUEST_KEYS[key]
            product_parms[key] = key_type(product_parms[key])

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'selection': json.dumps(product_parms)}

        response = await self._request('query', payload, wait=wait)
        return response['asinList']

    async def deals(self, deal_parms, domain='US', wait=True):
        """Query the Keepa API for product deals.

        You can find products that recently changed and match your
        search criteria.  A single request will return a maximum of
        150 deals.  Try ou the deals page to frist get accustomed to
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

        domain : str, optional
            One of the following Amazon domains: RESERVED, US, GB, DE,
            FR, JP, CA, CN, IT, ES, IN, MX Defaults to US.

        wait : bool, optional
            Wait available token before doing effective query, Defaults to ``True``.

        Examples
        --------
        >>> import keepa
        >>> api = await keepa.AsyncKeepa('ENTER_YOUR_KEY_HERE')
        >>> deal_parms = {"page": 0,
                          "domainId": 1,
                          "excludeCategories": [1064954, 11091801],
                          "includeCategories": [16310101]}
        >>> deals = await api.deals(deal_parms)
        >>> print(deals[:5])
            ['B00U20FN1Y', 'B078HR932T', 'B00L88ERK2',
             'B07G5TDMZ7', 'B00GYMQAM0']
        """
        # verify valid keys
        for key in deal_parms:
            if key not in DEAL_REQUEST_KEYS:
                raise RuntimeError('Invalid key "%s"' % key)

            # verify json type
            key_type = DEAL_REQUEST_KEYS[key]
            deal_parms[key] = key_type(deal_parms[key])

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'selection': json.dumps(deal_parms)}

        response = await self._request('query', payload, wait=wait)
        return response['asinList']

    async def _request(self, request_type, payload, wait=True):
        """Queries keepa api server.  Parses raw response from keepa
        into a json format.  Handles errors and waits for avaialbe
        tokens if allowed.
        """

        while True:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://api.keepa.com/%s/?' % request_type, params=payload
                ) as raw:
                    status_code = str(raw.status)
                    if status_code != '200':
                        if status_code in SCODES:
                            if status_code == '429' and wait:
                                await self.wait_for_tokens()
                                continue
                            else:
                                raise Exception(SCODES[status_code])
                        else:
                            raise Exception('REQUEST_FAILED')

                    response = await raw.json()

                    if 'error' in response:
                        if response['error']:
                            raise Exception(response['error']['message'])

                    # always update tokens
                    self.tokens_left = response['tokensLeft']
                    return response
            break


def convert_offer_history(csv, to_datetime=True):
    """Converts an offer history to human readable values.

    Parameters
    ----------
    csv : list
       Offer list csv obtained from ['offerCSV']

    to_datetime : bool, optional
        Modifies numpy minutes to datetime.datetime values.
        Default True.

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
    prices = values/100.0
    return times, prices


def keepa_minutes_to_time(minutes, to_datetime=True):
    """Accepts an array or list of minutes and converts it to a numpy
    datetime array.  Assumes that keepa time is from keepa minutes
    from ordinal.
    """

    # Convert to timedelta64 and shift
    dt = np.array(minutes, dtype='timedelta64[m]')
    dt = dt + KEEPA_ST_ORDINAL  # shift from ordinal

    # Convert to datetime if requested
    if to_datetime:
        return dt.astype(datetime.datetime)
    else:
        return dt


def run_and_get(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    task = loop.create_task(coro)
    loop.run_until_complete(task)
    return task.result()


class Keepa():
    """Class to support a Python interface to keepa server.

    Synchronous version of AsyncKeepa

    Initializes API with access key.  Access key can be obtained by
    signing up for a reoccurring or one time plan at:
    https://keepa.com/#!api

    Parameters
    ----------
    accesskey : str
        64 character access key string.

    Examples
    --------
    Create the api object

    >>> import keepa
    >>> mykey = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    >>> api = keepa.Keepa(mykey)

    Request data from two ASINs

    >>> products = api.query(['0439064872', '1426208081'])

    Print item details

    >>> print('Item 1')
    >>> print('\t ASIN: {:s}'.format(products[0]['asin']))
    >>> print('\t Title: {:s}'.format(products[0]['title']))

    Print item price

    >>> usedprice = products[0]['data']['MarketplaceUsed']
    >>> usedtimes = products[0]['data']['MarketplaceUsed_time']
    >>> print('\t Used price: ${:.2f}'.format(usedprice[-1]))
    >>> print('\t as of: {:s}'.format(str(usedtimes[-1])))
    """

    def __init__(self, accesskey):
        """ Initializes object """
        self.__dict__["parent"] = run_and_get(AsyncKeepa.create(accesskey))

    def __setattr__(self, attr, value):
        setattr(self.parent, attr, value)

    def __getattr__(self, attr):
        # properties
        if attr == "parent":
            return getattr(self, attr)
        if hasattr(self.parent, attr) and not callable(getattr(self.parent, attr)):
            return getattr(self.parent, attr)

        # methods
        def magic_method(*args, **kwargs):
            if not attr.startswith("__"):
                if hasattr(self.parent, attr) and callable(getattr(self.parent, attr)):
                    if asyncio.iscoroutinefunction(getattr(self.parent, attr)):
                        return run_and_get(getattr(self.parent, attr)(*args, **kwargs))
                    else:
                        return getattr(self.parent, attr)(*args, **kwargs)
        return magic_method
