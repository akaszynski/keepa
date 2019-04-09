"""
Interface module to download Amazon product and history data from
keepa.com
"""
import logging
import time
import datetime

import requests
import numpy as np

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
            -1. Including shipping costs.

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
    # https://github.com/keepacom/api_backend
    # see api_backend/src/main/java/com/keepa/api/backend/structs/Product.java
    # [index in csv, key name, isfloat (is price)]
    indices = [[0, 'AMAZON', True],
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

    product_data = {}

    for ind, key, isfloat in indices:
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
                values /= 10

            timeval = keepa_minutes_to_time(times, to_datetime)
            product_data['%s_time' % key] = timeval
            product_data[key] = values

    return product_data


def format_items(items):
    """ Checks if the input items are valid and formats them """
    if isinstance(items, list) or isinstance(items, np.ndarray):
        return np.unique(items)
    elif isinstance(items, str):
        return np.asarray([items])


class Keepa(object):
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
        self.accesskey = accesskey
        self.status = None

        # Store user's available tokens
        log.info('Connecting to keepa using key ending in %s' % accesskey[-6:])
        self.update_status()
        log.info('%d tokens remain' % self.tokens_left)

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

        # Return value in seconds
        return timetorefil / 1000.0

    def update_status(self):
        """ Updates available tokens """
        self.status = self._request('token', {'key': self.accesskey}, wait=False)

    def wait_for_tokens(self):
        """Checks any remaining tokens and waits if none are available.
        """
        self.update_status()

        # Wait if no tokens available
        if self.tokens_left <= 0:
            tdelay = self.time_to_refill
            print('Waiting %.2f seconds for additional tokens' % tdelay)
            time.sleep(tdelay)
            self.update_status()

    def query(self, items, stats=None, domain='US', history=True,
              offers=None, update=None, to_datetime=True,
              rating=False, out_of_stock_as_nan=True, stock=False,
              product_code_is_asin=True):
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

        Returns
        -------
        products : list

            See: https://keepa.com/#!discuss/t/product-object/116

            List of products.  Each product within the list is a
            dictionary.  The keys of each item may vary, so see the
            keys within each product for further details.

            Each product should contain at a minimum a "data" key
            containing a formatted dictonary with the following
            fields:

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
            log.debug('Executing %d item product query' % nitems)

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
            response = self._product_query(item_request,
                                           product_code_is_asin,
                                           stats=stats,
                                           domain=domain, stock=stock,
                                           offers=offers, update=update,
                                           history=history, rating=rating,
                                           to_datetime=to_datetime,
                                           out_of_stock_as_nan=out_of_stock_as_nan)
            idx += nrequest
            products.extend(response['products'])

        return products

    def _product_query(self, items, product_code_is_asin=True, **kwargs):
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
        response = self._request('product', kwargs)
        if kwargs['history']:
            for product in response['products']:
                if product['csv']:  # if data exists
                    product['data'] = parse_csv(product['csv'],
                                                to_datetime,
                                                out_of_stock_as_nan)
        return response

    def best_sellers_query(self, category, domain='US'):
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

        Returns
        -------
        best_sellers : list
            List of best seller ASINs
        """
        assert domain in DCODES, 'Invalid domain code'

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'category': category}

        response = self._request('bestsellers', payload)
        if 'bestSellersList' in response:
            return response['bestSellersList']['asinList']
        else:  # pragma: no cover
            log.info('Best sellers search results not yet available')

    def search_for_categories(self, searchterm, domain='US'):
        """
        Searches for categories from Amazon.

        Parameters
        ----------
        searchterm : str
            Input search term.

        Returns
        -------
        categories : list
            The response contains a categories list with all matching
            categories.

        Examples
        --------
        Print all categories from science
        >>> categories = api.search_for_categories('science')
        >>> for cat_id in categories:
        >>>    print(cat_id, categories[cat_id]['name'])

        """
        assert domain in DCODES, 'Invalid domain code'

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'type': 'category',
                   'term': searchterm}

        response = self._request('search', payload)
        if response['categories'] == {}:  # pragma no cover
            raise Exception('Categories search results not yet available ' +
                            'or no search terms found.')
        else:
            return response['categories']

    def category_lookup(self, category_id, domain='US', include_parents=0):
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

        Returns
        -------
        categories : list
            Output format is the same as search_for_categories.

        Examples
        --------
        Use 0 to return all root categories
        >>> categories = api.category_lookup(0)

        # Print all root categories
        >>> for cat_id in categories:
        >>>    print(cat_id, categories[cat_id]['name'])
        """
        assert domain in DCODES, 'Invalid domain code'

        payload = {'key': self.accesskey,
                   'domain': DCODES.index(domain),
                   'category': category_id,
                   'parents': include_parents}

        response = self._request('category', payload)
        if response['categories'] == {}:  # pragma no cover
            raise Exception('Category lookup results not yet available or no' +
                            'match found.')
        else:
            return response['categories']

    def seller_query(self, seller_id, domain='US'):
        """
        Receives seller information for a given seller id.  If a
        seller is not found no tokens will be consumed.

        Token cos: 1 per requested seller

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

        Returns
        -------
        seller_info : dict
            Dictionary containing one entry per input seller_id.

        Examples
        --------
        >>> seller_info = api.seller_query('A2L77EE7U53NWQ', 'US')

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
        return self._request('seller', payload)['sellers']

    def _request(self, request_type, payload, wait=True):
        """Queries keepa api server.  Parses raw response from keepa into
        a json format.  Handles errors and waits for avaialbe tokens if
        allowed.
        """
        if wait:
            self.wait_for_tokens()

        while True:
            raw = requests.get('https://api.keepa.com/%s/?' % request_type, payload)
            status_code = str(raw.status_code)
            if status_code != '200':
                if status_code in SCODES:
                    if status_code == '429' and wait:
                        print('waiting for tokens')
                        time.sleep(self.wait_for_tokens())
                    raise Exception(SCODES[status_code])
                else:
                    raise Exception('REQUEST_FAILED')
            break

        response = raw.json()
        if 'error' in response:
            if response['error']:
                raise Exception(response['error']['message'])

        # always update tokens
        self.tokens_left = response['tokensLeft']
        return response


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
