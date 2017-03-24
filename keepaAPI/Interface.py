# -*- coding: utf-8 -*-
"""
Interface module to download Amazon product and history data from keepa.com

"""

# Standard library
import logging

# for IPython
try:
    reload(logging)
except:
    pass

import time
import threading

# Other libraries
import requests
import numpy as np

# This module
from keepaAPI import keepaTime

# Disable logging in requests module
logging.getLogger("requests").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# percent encoding
import sys
import urllib
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
# Valid values: [ 1: com | 2: co.uk | 3: de | 4: fr | 5: co.jp | 6: ca | 7: cn | 8: it | 9: es | 10: in | 11: com.mx ]
dcodes = ['RESERVED', 'US', 'GB', 'DE', 'FR', 'JP', 'CA', 'CN', 'IT', 'ES', 
          'IN', 'MX']


def ThreadRequest(asins, settings, products, sema, err):
    """
    Function to send query to keepa and store results

    Supports threads
    
    """

    # Attempt request
    try:
        try:
            response = ProductQuery(asins, settings)
            products.extend(response['products'])
        except Exception as e:
            logging.warning('Exception {:s} in thread.  Waiting 60 seconds for retry.'.format(e))
            time.sleep(60)
            
            # Try again
            response = ProductQuery(asins, settings)
            products.extend(response['products'])
            
    except:
        # Track error
        err = True

    # Log
    if not err:
        logging.info('Completed {:d} ASIN(s)'.format(len(products)))
    else:
        logging.err('Request failed')
        
    # finally, release thread
    sema.release()
    

def GetUserStatus(accesskey):
    """ Queries keepa for available tokens """
    
    url = 'https://api.keepa.com/token/?key={:s}'.format(accesskey)
    r = requests.get(url)
    status_code = r.status_code
    
    # Return parsed response if successful
    if status_code == 200:
        response =  r.json()
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
        t = int(time.time()*1000)

        # Number of times refill has occured
        lstrefil = self.status['timestamp'] - (60000 - self.status['refillIn'])
        nrefil = (t - lstrefil)/60000.0

        if nrefil > 1:
            self.status['tokensLeft'] += self.status['refillRate']*int(nrefil)
            
            if self.status['tokensLeft'] > 60*self.status['refillRate']:
                self.status['tokensLeft'] = 60*self.status['refillRate']

        # Update timestamps
        self.status['timestamp'] = t
        self.status['refillIn'] = int((1 - nrefil % 1)*60000)


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
        now = int(time.time()*1000)
        timeatrefile = self.status['timestamp'] + self.status['refillIn']
        
        timetorefil = timeatrefile - now + 1000 # plus one second fudge factor
        if timetorefil < 0:
            timetorefil = 0
            
        # Return value in seconds
        return timetorefil/1000.0


    def UpdateFromResponse(self, response):
        """ Updates user status from response """
        for key in self.status:
            self.status[key] = response[key]


def ProductQuery(asins, settings):
    """
    Sends query to keepa API and returns parsed JSON result
    
    INPUTS
    
    Required:
        asins (np.ndarray)
            Array of ASINs.  Must be between 1 and 100 ASINs
        settings (dictonary) containing: 

            accesskey: (string)
                keepa access key string

            domain: (string)
                One of the following Amazon domains:
                RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
                
            offers (bool default False)
                Adds product offers to product data

            update (int default None)
                If data is older than the input interger, keepa will update
                their database and return live data.  If set to 0 (live data),
                then request may cost an additional token

            history (bool default True)
                When set to True includes the price, sales, and offer history
                of a product.  Set to False to reduce request time if data is
                not required
    
    OUTPUTS
    Response, if successful, will contain the following fields
        n

        products
            Dictionary of product data.  Length equal to number of successful
            ASINs

        refillIn
            Time in miliseconds to the next refill of tokens

        refilRate
            Number of tokens refilled per minute

        timestamp
        
        tokensLeft
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

    if settings['offers']:
        payload['offers'] = settings['offers']
        
    if settings['update'] != None:
        payload['update'] = int(settings['update'])
        
    if not settings['history']:
        payload['history'] = 0
   
    r = requests.get('https://api.keepa.com/product/?', params=payload)
    status_code = r.status_code

    # Return parsed response if successful
    if status_code == 200:
        # Parse JSON response
        response =  r.json()
        
        # Replace csv with parsed data if history enabled
        if settings['history']:
            for product in response['products']:
                if product['csv']: # if data exists
                    product['data'] = ParseCSV(product['csv'], settings['to_datetime'])
                    del product['csv']
            
        return response

    elif str(status_code) in scodes:
        raise Exception(scodes[str(status_code)])
        
    else:
        raise Exception('REQUEST_FAILED')


def ParseCSV(csv, to_datetime):
    """
    
    Parses csv list from keepa into a python dictionary
    
    csv is organized as the following
        index   item
        0       Amazon Price
        1       Marketplace New
        2       Marketplace Used
        3       Sales Rank
        4       Listing Price
        5       Collectable Price
        11      New Offers
        12      Used Offers
        14      Collectable Offers
    
    
    """
    
    # index in csv, key name, isfloat (is price)
    indices = [[0, 'AmazonPrice', True],
               [1, 'MarketplaceNew', True],
               [2, 'MarketplaceUsed', True],
               [3, 'SalesRank', False],
               [4, 'ListingPrice', True],
               [5, 'CollectablePrice', True],
               [11, 'NewOffers', False],
               [12, 'UsedOffers', False],
               [14, 'CollectableOffers', False]]


    product_data = {}
    
    for index in indices:
        # Check if it exists
        ind = index[0]
        if csv[ind]:
            key = index[1]
            
            # Data goes [time0, value0, time1, value1, ...]
            product_data[key + '_time'] = keepaTime.KeepaMinutesToTime(csv[ind][::2], to_datetime)

            # Convert to float price if applicable
            if index[2]:
                product_data[key] = np.array(csv[ind][1::2], np.float)/100.0
            else:
                product_data[key] = np.asarray(csv[ind][1::2])

    return product_data


def CheckASINs(asins):
    """ Checks if the input ASINs are valid and formats them """
    if isinstance(asins, list) or isinstance(asins, np.ndarray):
        return np.unique(asins)

    elif isinstance(asins, str) or isinstance(asins, unicode):
        if len(asins) != 10:
            return np.array([])
        else:
            return np.asarray([asins])

#==============================================================================
# Main API
#==============================================================================
class API(object):
    """
    Class to support html interface to keepa server.
    
    EXAMPLE
    import keepaAPI
    
    # Access key from https://keepa.com/#!api  (this key does not work)
    mykey = 'e1aazzz26f8e0ecebzzz15416a0zzz61310a3b66ac7c6935c348894008a56021'
    
    # Create API
    api = keepaAPI.API(mykey) 
    
    # Request data from two ASINs
    products = api.ProductQuery(['0439064872', '1426208081'])
    
    # Print item details
    print('Item 1')
    print('\t ASIN: {:s}'.format(products[0]['asin']))
    print('\t Title: {:s}'.format(products[0]['title']))
    
    # Print item price
    usedprice = products[0]['data']['MarketplaceUsed']
    usedtimes = products[0]['data']['MarketplaceUsed_time']
    print('\t Used price: ${:.2f}'.format(usedprice[-1]))
    print('\t as of: {:s}'.format(str(usedtimes[-1])))
    
    """
    
    def __init__(self, accesskey, log=True):
        """ 
        DESCRITPION
        
        Initializes API with access key.  Access key can be obtained by signing
        up for a reoccuring or one month plan at https://keepa.com/#!api
        
        INPUTS
        accesskey (string)
            64 character string.  Example string (does not work):
            e1aazzz26f8e0ecebzzz15416a0zzz61310a3b66ac7c6935c348894008a56021
    
        logging (bool, default False)
            Controls if logging requests are printed to screen.  Default True.
        
        OUTPUTS
        None
        
        """
    
        # Create logger
        if log:
            logstr = '%(levelname)-7s: %(message)s'
            logging.basicConfig(format=logstr, level='DEBUG', filename='')
            logging.info('Connecting to keepa using key {:s}'.format(accesskey))

        # Store access key
        self.accesskey = accesskey

        # Store user's available tokens
        self.user = UserStatus(self.accesskey)
        logging.info('{:d} tokens remain'.format(self.user.RemainingTokens()))


    def WaitForTokens(self, updatetype='server'):
        """
        DESCRIPTION
        Checks local user status for any remaining tokens and waits if none are
        available
        
        INPUTS
        updatetype (string, default 'server')
            Updates available tokens based on a client side update or server
            side update.  Input 'client' for a client side update
        
        """
        
        if updatetype=='server':
            # Perform server update
            self.user.UpdateFromServer()
        else:
            # Perform local update
            self.user.LocalUpdate()

        # Wait if no tokens available
        if self.user.RemainingTokens() <= 0:
            tdelay = self.user.TimeToRefill()
            logging.info('Waiting {:.2f} seconds for additional tokens'.format(tdelay))
            time.sleep(tdelay)
            self.user.LocalUpdate()


    def ProductQuery(self, asins, domain='US', history=True, offers=None,
                     update=None, nthreads=4, to_datetime=True):
        """
        DESCRIPTION
        Performs a product query of a list, array, or single ASIN.  Returns a
        list of product data with one entry for each product.
        
        INPUTS:
        asins (string or list or np.ndarray)
            A list, array, or single ASIN.  Each ASIN should be 10
            characters and match a product on Amazon.  ASINs not matching
            Amazon product or duplicate ASINs will return no data.
        
        domain (string, default 'US')
            One of the following Amazon domains:
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
            
        offers (int, default None)
            Adds available offers to product data

        update (int default None)
            If data is older than the input interger, keepa will update
            their database and return live data.  If set to 0 (live data),
            then request may cost an additional token

        history (bool, default True)
            When set to True includes the price, sales, and offer history
            of a product.  Set to False to reduce request time if data is
            not required
            
        nthreads (int, default 4)
            Number of threads to interface to keepa with.  More threads
            means potentially faster batch response, but more bandwidth.
            Probably should be kept under 20.
            
        to_datetime (bool, default True)
            Modifies numpy minutes to datetime.datetime values.
        
        OUTPUTS
        products (list)
            List of products.  Each product within the list is a dictionary.
            The keys of each item may vary, so see the keys within each product
            for further details.
            
        
        """
        # Format asins into numpy array
        try:
            asins = CheckASINs(asins)
        except:
            raise Exception('Invalid ASIN input')

        nitems = len(asins)
        if nitems == 1:
            logging.info('EXECUTING SINGLE PRODUCT QUERY'.format(nitems))
        else:
            logging.info('EXECUTING {:d} ITEM PRODUCT QUERY'.format(nitems))

        # Update user status and determine if there any tokens available
        self.user.UpdateFromServer()
        
        # Assemble settings
        settings = {'domain': domain,
                    'accesskey': self.accesskey,
                    'offers': offers,
                    'update': None,
                    'history': history,
                    'to_datetime': to_datetime}
        
        # Report time to completion
        tcomplete = float(nitems - self.user.RemainingTokens())/self.user.status['refillRate'] - (60000 - self.user.status['refillIn'])/60000.0
        if tcomplete < 0.0:
            tcomplete = 0.5
        logging.info('Estimated time to complete {:d} request(s) is {:.2f} minutes'.format(len(asins), tcomplete))
        logging.info('\twith a refill rate of {:d} token(s) per minute'.format(self.user.status['refillRate']))

        # initialize product and thread lists
        products = []
        threads = []
        
        # Error tracking
        err = False        
        
        # Create thread pool
        sema = threading.BoundedSemaphore(value=nthreads)
    
        # Number of requests is dependent on the number of items and request limit
        # Use available tokens first
        idx = 0 # or number complete
        while idx < nitems:

            # listen for error
            if err:
                raise Exception ('Error in thread')

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
            sema.acquire() # Limit to nthreads.  Wait if requesting more
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
        DESCRIPTION
        Retrieve an ASIN list of the most popular products based on sales in a 
        specific category or product group.  See "SearchForCategories" for
        information on how to get a category.

        Root category lists (e.g. "Home & Kitchen") or product group lists 
        contain up to 30,000 ASINs.
        
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
        
        
        INPUTS
        categoryId (string)
            The category node id of the category you want to request the best 
            sellers list for. You can find category node ids via the category 
            search  "SearchForCategories"
            
        domain: (optional string)
            Amazon locale you want to access. Must be one of the following
            RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
            
        OUTPUTS
        bestSellersList (list)
            List of best seller ASINs
            
        EXAMPLE
        api.BestSellersQuery
            
            
        """
        
        if domain not in dcodes:
            raise Exception('Invalid domain code')
        
        payload = {'key': self.accesskey,
                   'domain': dcodes.index(domain), 
                   'category': category}
        
        r = requests.get('https://api.keepa.com/bestsellers/?', params=payload)
        response =  r.json()
        
        if 'bestSellersList' in response:
            return response['bestSellersList']['asinList']
        else:
            logging.info('Best sellers search results not yet available')


    def SearchForCategories(self, searchterm, domain='US'):
        """
        DESCRIPTION
        
        EXAMPLE
        categories = api.SearchForCategories('science')
        
        # Print all categories
        for catId in categories:
            print(catId, categories[catId]['name'])
        
        
        INPUT
        searchterm (string)
            Input search term.  
        
        
        OUTPUT
        categories (list)
            The response contains a categories list with all matching categories.

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
            logging.info('Categories search results not yet available')
        else:
            return response['categories']
    
    
    def GetAvailableTokens(self):
        """ Returns available tokens """
        return self.user.RemainingTokens()
        