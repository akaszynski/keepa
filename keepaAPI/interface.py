"""
Interface module to download Amazon product and history data from keepa.com
"""
import logging
import time
import threading
import sys
import urllib
import warnings

import requests
import numpy as np

from keepaAPI import keepaTime

log = logging.getLogger(__name__)
log.setLevel('DEBUG')

# percent encoding
if sys.version_info[0] == 2:
    quote_plus = urllib.quote
else:
    quote_plus = urllib.parse.quote

# Request limit
reqlim = 100

# Status code dictionary/key
scodes = {'400': 'REQUEST_REJECTED',
          '402': 'PAYMENT_REQUIRED',
          '405': 'METHOD_NOT_ALLOWED',
          '429': 'NOT_ENOUGH_TOKEN'}

# domain codes
# Valid values: [ 1: com | 2: co.uk | 3: de | 4: fr | 5:
#                 co.jp | 6: ca | 7: cn | 8: it | 9: es | 10: in | 11: com.mx ]
dcodes = ['RESERVED', 'US', 'GB', 'DE', 'FR', 'JP', 'CA', 'CN', 'IT', 'ES',
          'IN', 'MX']


def ThreadRequest(asins, settings, products, sema, err, max_try=5):
    """
    Function to send query to keepa and store results

    Supports threads

    """

    # Attempt request
    response = None
    ntry = 0
    while response is None:
        try:
            response = ProductQuery(asins, settings)
            products.extend(response['products'])
        except Exception as e:
            log.warning('Exception %s in thread.  Waiting 60 seconds for retry.' % e)
            time.sleep(60)

        ntry += 1
        if ntry > max_try:
            break

    if response is None:
        log.error('Request for asins %s failed' % str(asins))
        err[0] = True  # store error occured
    else:
        log.info('Completed %d ASIN(s)' % len(products))

    # finally, release thread
    sema.release()


def GetUserStatus(accesskey):
    """ Queries keepa for available tokens """

    url = 'https://api.keepa.com/token/?key={:s}'.format(accesskey)
    r = requests.get(url)
    status_code = r.status_code

    # Return parsed response if successful
    if status_code == 200:
        response = r.json()
        return response

    elif str(status_code) in scodes:
        raise Exception(scodes[str(status_code)])
    else:
        raise Exception('REQUEST_FAILED')


class UserStatus(object):
    """ Object to track and store user status on keepa locally """

    def __init__(self, accesskey):
        """ Initialize user status using server side info """
        self.accesskey = accesskey
        self.UpdateFromServer()

    def UpdateFromServer(self):
        """ Update user status from server """
        self.status = GetUserStatus(self.accesskey)

    def LocalUpdate(self):
        """
        Update the local user status using existing timestamp and refill rate
        """

        # Get current timestamp in miliseconds from unix epoch
        t = int(time.time() * 1000)

        # Number of times refill has occured
        lstrefil = self.status['timestamp'] - (60000 - self.status['refillIn'])
        nrefil = (t - lstrefil) / 60000.0

        if nrefil > 1:
            self.status['tokensLeft'] += self.status['refillRate'] * \
                int(nrefil)

            if self.status['tokensLeft'] > 60 * self.status['refillRate']:
                self.status['tokensLeft'] = 60 * self.status['refillRate']

        # Update timestamps
        self.status['timestamp'] = t
        self.status['refillIn'] = int((1 - nrefil % 1) * 60000)

    def RemoveTokens(self, tokens):
        """ Remove tokens from tokensLeft to track requests to server """
        self.LocalUpdate()
        self.status['tokensLeft'] -= tokens

    def RemainingTokens(self):
        """ Returns the tokens remaining to the user """
        return self.status['tokensLeft']

    def TimeToRefill(self, ):
        """ Returns the time to refill in seconds """
        # Get current timestamp in miliseconds from unix epoch
        now = int(time.time() * 1000)
        timeatrefile = self.status['timestamp'] + self.status['refillIn']

        timetorefil = timeatrefile - now + 1000  # plus one second fudge factor
        if timetorefil < 0:
            timetorefil = 0

        # Return value in seconds
        return timetorefil / 1000.0

    def UpdateFromResponse(self, response):
        """ Updates user status from response """
        for key in self.status:
            self.status[key] = response[key]


def ProductQuery(asins, settings):
    """
    Sends query to keepa API and returns parsed JSON result

    Parameters
    ----------
    asins : np.ndarray
        Array of ASINs.  Must be between 1 and 100 ASINs
    settings (dictonary) containing:

    accesskey : str
        keepa access key string

    stats : int or date format
        Set the stats time for get sales rank inside this range

    domain : str
        One of the following Amazon domains:
        RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX

    offers : bool, optional
        Adds product offers to product data.  Default False

    update : int, optional
        If data is older than the input interger, keepa will update
        their database and return live data.  If set to 0 (live data),
        then request may cost an additional token.

    history : bool, optional
        When set to True includes the price, sales, and offer history
        of a product.  Set to False to reduce request time if data is
        not required.

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

    tz
        Timezone.  0 is UTC

    """
    # ASINs convert to comma joined string
    nitems = len(asins)
    if nitems > 100:
        raise Exception('Too many items in product query')
    asinstr = ','.join(asins)

    # Assemble and send request
    # Accepts gzip encoding and defaults with no cache
    payload = {'key': settings['accesskey'],
               'domain': dcodes.index(settings['domain']),
               'asin': asinstr}

    if settings['stats']:
        payload['stats'] = settings['stats']

    # This seems to only work when it's a large number.
    if settings['offers']:
        payload['offers'] = 1000

    if settings['update'] is not None:
        payload['update'] = int(settings['update'])

    if not settings['history']:
        payload['history'] = 0

    if settings['rating']:
        payload['rating'] = 1

    r = requests.get('https://api.keepa.com/product/?', params=payload)
    status_code = r.status_code

    # Return parsed response if successful
    if status_code == 200:
        # Parse JSON response
        response = r.json()

        # Replace csv with parsed data if history enabled
        if settings['history']:
            for product in response['products']:
                if product['csv']:  # if data exists
                    product['data'] = ParseCSV(
                        product['csv'], settings['to_datetime'])

        return response

    elif str(status_code) in scodes:
        raise Exception(scodes[str(status_code)])

    else:
        raise Exception('REQUEST_FAILED')


def ParseCSV(csv, to_datetime=True):
    """Parses csv list from keepa into a python dictionary

    Parameters
    ----------
    csv : list
        csv list from keepa

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

    """
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
               [30, 'TRADE_IN', True]]

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

            if isfloat:  # Convert to float price if applicable
                nanmask = values < 0
                values = values.astype(np.float)/100
                values[nanmask] = np.nan

            if key == 'RATING':
                values /= 10

            timeval = keepaTime.KeepaMinutesToTime(times, to_datetime)
            product_data['%s_time' % key] = timeval
            product_data[key] = values

    return product_data


def CheckASINs(asins):
    """ Checks if the input ASINs are valid and formats them """
    if isinstance(asins, list) or isinstance(asins, np.ndarray):
        return np.unique(asins)

    elif isinstance(asins, str):  # or isinstance(asins, unicode):
        if len(asins) != 10:
            return np.array([])
        else:
            return np.asarray([asins])


class API(object):
    """
    Class to support html interface to keepa server.

    Initializes API with access key.  Access key can be obtained by signing
    up for a reoccuring or one month plan at https://keepa.com/#!api

    Parameters
    ----------
    accesskey : string
        64 character string.  Example string (does not work):
        e1aazzz26f8e0ecebzzz15416a0zzz61310a3b66ac7c6935c348894008a56021

    logging : depreciated
        Depreciated


    Examples
    --------
    Create the api object
    Access key from https://keepa.com/#!api  (this key does not work)
    >>> import keepaAPI
    >>> mykey = 'e1aazzz26f8e0ecebzzz15416a0zzz61310a3b66ac7c6935c348894008a56021'
    >>> # Create API
    >>> api = keepaAPI.API(mykey)

    Request data from two ASINs
    >>> products = api.ProductQuery(['0439064872', '1426208081'])

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

    def __init__(self, accesskey, logging=None):
        """ Initializes object """
        if logging:
            warnings.warn('logging parameter is depreciated')

        # Store access key
        self.accesskey = accesskey

        # Store user's available tokens
        self.user = UserStatus(self.accesskey)
        log.info('Connecting to keepa using key ending in %s' % accesskey[-6:])
        log.info('%d tokens remain' % self.user.RemainingTokens())

    def WaitForTokens(self, updatetype='server'):
        """
        Checks local user status for any remaining tokens and waits if none are
        available

        Parameters
        ----------
        updatetype : string, optional
            Updates available tokens based on a client side update or server
            side update.  Input 'client' for a client side update.  Defaults
            to 'server'.
        """

        if updatetype == 'server':
            # Perform server update
            self.user.UpdateFromServer()
        else:
            # Perform local update
            self.user.LocalUpdate()

        # Wait if no tokens available
        if self.user.RemainingTokens() <= 0:
            tdelay = self.user.TimeToRefill()
            log.info(
                'Waiting {:.2f} seconds for additional tokens'.format(tdelay))
            time.sleep(tdelay)
            self.user.LocalUpdate()

    def ProductQuery(self, asins, stats=None, domain='US', history=True,
                     offers=0, update=None, nthreads=4, to_datetime=True,
                     rating=False, allow_errors=False):
        """
        Performs a product query of a list, array, or single ASIN.  Returns a
        list of product data with one entry for each product.

        Parameters
        ----------
        asins : string,  list, np.ndarray
            A list, array, or single ASIN.  Each ASIN should be 10
            characters and match a product on Amazon.  ASINs not matching
            Amazon product or duplicate ASINs will return no data.

        stats : int or date, optional
            No extra token cost. If specified the product object will have a
            stats field with quick access to current prices, min/max prices
            and the weighted mean values. If the offers parameter was used it
            will also provide stock counts and buy box information.

            You can provide the stats parameter in two forms:

            Last x days (positive integer value): calculates the stats of
            the last x days, where x is the value of the stats parameter.
            Interval: You can provide a date range for the stats
            calculation. You can specify the range via two timestamps
            (unix epoch time milliseconds) or two date strings (ISO8601,
            with or without time in UTC).

        domain : string, optional
            One of the following Amazon domains:
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
            Defaults to US.

        offers : int, optional
            Adds available offers to product data.  Default 0.  Must be between 
            20 and 100.

        update : int, optional
            If data is older than the input interger, keepa will update
            their database and return live data.  If set to 0 (live data),
            request may cost an additional token.  Default None

        history : bool, optional
            When set to True includes the price, sales, and offer history
            of a product.  Set to False to reduce request time if data is
            not required.  Default True

        rating : bool, optional
            When set to to True, includes the existing RATING and COUNT_REVIEWS
            history of the csv field.  Default False

        nthreads : int, optional
            Number of threads to interface to keepa with.  More threads
            means potentially faster batch response, but more bandwidth.
            Probably should be kept under 20.  Default 4

        to_datetime : bool, optional
            Modifies numpy minutes to datetime.datetime values.  Default True.

        allow_errors : bool, optional
            Permits errors in requests.  List of products may not match input
            asin list.

        Returns
        -------
        products : list

            See: https://keepa.com/#!discuss/t/product-object/116

            List of products.  Each product within the list is a dictionary.
            The keys of each item may vary, so see the keys within each product
            for further details.

            Each product should contain at a minimum a "data" key containing
            a formatted dictonary with the following fields:

        Notes
        -----
        The following are data fields a product dictionary

        AMAZON
            Amazon price history

        NEW
            Marketplace/3rd party New price history - Amazon is considered to
            be part of the marketplace as well, so if Amazon has the overall
            lowest new (!) price, the marketplace new price in the
            corresponding time interval will be identical to the Amazon price
            (except if there is only one marketplace offer).  Shipping and
            Handling costs not included!

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
            3rd party (not including Amazon) New price history including
            shipping costs, only fulfilled by merchant (FBM).

        LIGHTNING_DEAL
            3rd party (not including Amazon) New price history including
            shipping costs, only fulfilled by merchant (FBM).

        WAREHOUSE
            Amazon Warehouse Deals price history. Mostly of used condition,
            rarely new.

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
             The product's rating history. A rating is an integer from 0 to 50
             (e.g. 45 = 4.5 stars)

        COUNT_REVIEWS
            The product's review count history.

        BUY_BOX_SHIPPING(18, true, false, true, true),
            The price history of the buy box. If no offer qualified for the buy
            box the price has the value -1. Including shipping costs.

        USED_NEW_SHIPPING(19, true, true, true, true),
            "Used - Like New" price history including shipping costs.

        USED_VERY_GOOD_SHIPPING(20, true, true, true, true),
            "Used - Very Good" price history including shipping costs.

        USED_GOOD_SHIPPING(21, true, true, true, true),
            "Used - Good" price history including shipping costs.

        USED_ACCEPTABLE_SHIPPING(22, true, true, true, true),
            "Used - Acceptable" price history including shipping costs.

        COLLECTIBLE_NEW_SHIPPING(23, true, true, true, true),
            "Collectible - Like New" price history including shipping costs.

        COLLECTIBLE_VERY_GOOD_SHIPPING(24, true, true, true, true),
            "Collectible - Very Good" price history including shipping costs.

        COLLECTIBLE_GOOD_SHIPPING(25, true, true, true, true),
            "Collectible - Good" price history including shipping costs.

        COLLECTIBLE_ACCEPTABLE_SHIPPING(26, true, true, true, true),
            "Collectible - Acceptable" price history including shipping costs.

        REFURBISHED_SHIPPING
            Refurbished price history including shipping costs.

        TRADE_IN
            The trade in price history. Amazon trade-in is not available for
            every locale.

        """
        # Format asins into numpy array
        try:
            asins = CheckASINs(asins)
        except BaseException:
            raise Exception('Invalid ASIN input')

        nitems = len(asins)
        if nitems == 1:
            log.info('Executing single product query'.format(nitems))
        else:
            log.info('Executing {:d} item product query'.format(nitems))

        # Update user status and determine if there any tokens available
        self.user.UpdateFromServer()

        # check offer input
        if offers:
            if not isinstance(offers, int):
                try:
                    offers = int(offers)
                except:
                    raise Exception('Parameter "offers" must be an interger')

            if offers > 100 or offers < 20:
                raise Exception('Parameter "offers" must be between 20 and 100')

        # Assemble settings
        settings = {'stats': stats,
                    'domain': domain,
                    'accesskey': self.accesskey,
                    'offers': offers,
                    'update': None,
                    'history': history,
                    'rating': rating,
                    'to_datetime': to_datetime}

        # Report time to completion
        tcomplete = float(
            nitems - self.user.RemainingTokens()) / self.user.status['refillRate'] - (
            60000 - self.user.status['refillIn']) / 60000.0
        if tcomplete < 0.0:
            tcomplete = 0.5
        log.info(
            'Estimated time to complete {:d} request(s) is {:.2f} minutes'.format(
                len(asins), tcomplete))
        log.info(
            '\twith a refill rate of {:d} token(s) per minute'.format(
                self.user.status['refillRate']))

        # initialize product and thread lists
        products = []
        threads = []

        # Error tracking
        err = [False]

        # Create thread pool
        sema = threading.BoundedSemaphore(value=nthreads)

        # Number of requests is dependent on the number of items and request limit
        # Use available tokens first
        idx = 0  # or number complete
        while idx < nitems:

            # listen for error
            if not allow_errors:
                if err[0]:
                    raise Exception('Error in thread')

            # Check and then wait for tokens if applicable
            self.WaitForTokens('local')

            nrequest = nitems - idx
            if nrequest > self.user.RemainingTokens():
                nrequest = self.user.RemainingTokens()
            if nrequest > reqlim:
                nrequest = reqlim

            # Increment, assemble request, and update available tokens
            asin_request = asins[idx:idx + nrequest]
            idx += nrequest
            self.user.RemoveTokens(nrequest)

            # Request data from server
            # Assemble partial array of ASINs for this request
            sema.acquire()  # Limit to nthreads.  Wait if requesting more
            t = threading.Thread(target=ThreadRequest, args=(asin_request,
                                                             settings,
                                                             products, sema,
                                                             err))
            t.start()
            threads.append(t)

        # Wait for all threads to complete before returning products
        for t in threads:
            t.join()

        return products

    def BestSellersQuery(self, category, domain='US'):
        """
        Retrieve an ASIN list of the most popular products based on sales in a
        specific category or product group.  See "SearchForCategories" for
        information on how to get a category.

        Root category lists (e.g. "Home & Kitchen") or product group lists
        contain up to 100,000 ASINs.

        Sub-category lists (e.g. "Home Entertainment Furniture") contain up to
        3,000 ASINs. As we only have access to the product's primary sales rank
        and not the ones of all categories it is listed in, the sub-category
        lists are created by us based on the product's primary sales rank and
        do not reflect the actual ordering on Amazon.

        Lists are ordered, starting with the best selling product.

        Lists are updated daily.
        If a product does not have an accessible sales rank it will not be
        included in the lists. This in particular affects many products in the
        Clothing and Sports & Outdoors categories.

        We can not correctly identify the sales rank reference category in all
        cases, so some products may be misplaced.

        Parameters
        ----------
        categoryId : string
            The category node id of the category you want to request the best
            sellers list for. You can find category node ids via the category
            search  "SearchForCategories"

        domain : string
            Amazon locale you want to access. Must be one of the following
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
            Default US

        Returns
        -------
        bestSellersList : list
            List of best seller ASINs
        """
        if domain not in dcodes:
            raise Exception('Invalid domain code')

        payload = {'key': self.accesskey,
                   'domain': dcodes.index(domain),
                   'category': category}

        r = requests.get('https://api.keepa.com/bestsellers/?', params=payload)
        response = r.json()

        if 'bestSellersList' in response:
            return response['bestSellersList']['asinList']
        else:
            log.info('Best sellers search results not yet available')

    def SearchForCategories(self, searchterm, domain='US'):
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
        >>> categories = api.SearchForCategories('science')
        >>> for catId in categories:
        >>>    print(catId, categories[catId]['name'])

        """
        # Check if valid domain
        if domain not in dcodes:
            raise Exception('Invalid domain code')

        payload = {'key': self.accesskey,
                   'domain': dcodes.index(domain),
                   'type': 'category',
                   'term': searchterm}

        r = requests.get('https://api.keepa.com/search/?', params=payload)
        response = r.json()

        if response['categories'] == {}:
            log.info('Categories search results not yet available or no ' +
                     'search terms found.')
        else:
            return response['categories']

    def CategoryLookup(self, categoryId, domain='US', includeParents=0):
        """
        Return root categories given a categoryId.

        Parameters
        ----------
        categoryId (integer)
            ID for specific category or 0 to return a list of root categories.

        Returns
        -------
        categories : list
            Output format is the same as SearchForCategories.

        Examples
        --------
        # use 0 to return all root categories
        categories = api.CategoryLookup(0)

        # Print all root categories
        for catId in categories:
            print(catId, categories[catId]['name'])
        """
        # Check if valid domain
        if domain not in dcodes:
            raise Exception('Invalid domain code')

        payload = {'key': self.accesskey,
                   'domain': dcodes.index(domain),
                   'category': categoryId,
                   'parents': includeParents}

        r = requests.get('https://api.keepa.com/category/?', params=payload)
        response = r.json()

        if response['categories'] == {}:
            logging.info('Category lookup results not yet available or no' +
                         'match found.')
        else:
            return response['categories']

    def GetAvailableTokens(self):
        """ Returns available tokens """
        return self.user.RemainingTokens()


def ConvertOfferHistory(csv, as_datetime=True):
    """
    Converts an offer history to human readable values

    Parameters
    ----------
    csv : list
       Offer list csv obtained from ['offerCSV']

    Returns
    -------
    times : numpy.ndarray
        List of time values for an offer history.

    prices : numpy.ndarray
        Price (including shipping) of an offer for each time at an index 
        of times.

    """

    # convert these values to numpy arrays
    times = csv[::3]
    values = np.array(csv[1::3])
    values += np.array(csv[2::3])  # add in shipping

    # convert to dollars and datetimes
    to_datetime = True
    times = keepaTime.KeepaMinutesToTime(times, to_datetime)
    prices = values/100.0

    return times, prices
