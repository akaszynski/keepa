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
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Request limit
reqlim = 100

# Status code dictionary/key
scodes = {'400': 'REQUEST_REJECTED',
          '402': 'PAYMENT_REQUIRED',
          '405': 'METHOD_NOT_ALLOWED',
          '429': 'NOT_ENOUGH_TOKEN'}

dcodes = ['RESERVED', 'US', 'GB', 'DE', 'FR', 'JP', 'CA', 'CN', 'IT', 'ES', 'IN', 'MX']


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
        logging.info('Completed {:d} ASINs'.format(len(products)))
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
#        del response['n']
#        del response['tz']
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
    print r.url
    print len(r.text)
    status_code = r.status_code

    # Return parsed response if successful
    if status_code == 200:
        # Parse JSON response
        response =  r.json()
        
        # Replace csv with parsed data if history enabled
        if settings['history']:
            for product in response['products']:
                if product['csv']: # if data exists
                    product['data'] = ParseCSV(product['csv'])
                    del product['csv']
            
        return response

    elif str(status_code) in scodes:
        raise Exception(scodes[str(status_code)])
        
    else:
        raise Exception('REQUEST_FAILED')


def ParseCSV(csv):
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
            product_data[key + '_time'] = keepaTime.KeepaMinutesToTime(csv[ind][::2])

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

    elif isinstance(asins, str):
        if len(asins) != 10:
            return np.array([])
        else:
            return np.asarray([asins])

#==============================================================================
# Main API
#==============================================================================
class API(object):
    """ Class to support html interface to keepa server """
    
    def __init__(self, accesskey):
        """ Initializes API """
    
        # Disable logging (except for warnings) for requests module    
#        logging.getLogger("requests").setLevel(logging.WARNING)

        # Create logger
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
        Checks local user status for any remaining tokens and waits if none are
        available
        
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


    def ProductQuery(self, asins, domain='US', history=True, offers=False,
                     update=None, nthreads=4):
        """
        Performs a product query of a list, array, or single ASIN.  Returns a
        list of product data with one entry for each product.
        
        INPUTS:
            asins (required string list np.ndarray)
                A list, array, or single ASIN.  Each ASIN should be 10
                characters and match a product on Amazon.  ASINs not matching
                Amazon product or duplicate ASINs will return no data.
            
            domain: (optional string)
                One of the following Amazon domains:
                RESERVED, US, GB, DE, FR, JP, CA, CN, IT, ES, IN, MX
                
            offers (optional bool default False)
                Adds product offers to product data

            update (optional int default None)
                If data is older than the input interger, keepa will update
                their database and return live data.  If set to 0 (live data),
                then request may cost an additional token

            history (optional bool default True)
                When set to True includes the price, sales, and offer history
                of a product.  Set to False to reduce request time if data is
                not required
                
            nthreads (optional int default 4)
                Number of threads to interface to keepa with.  More threads
                means potentially faster batch response, but more bandwidth.
                Probably should be kept under 20.
        
        """
        # Format asins into numpy array
        try:
            asins = CheckASINs(asins)
        except:
            raise Exception('Invalid ASIN input.')

        nitems = len(asins)
        logging.info('EXECUTING {:d} ITEM PRODUCT QUERY'.format(nitems))

        # Update user status and determine if there any tokens available
        self.user.UpdateFromServer()
        
        # Assemble settings
        settings = {'domain': domain,
                    'accesskey': self.accesskey,
                    'offers': offers,
                    'update': None,
                    'history': history}
        
        # Report time to completion
        tcomplete = float(nitems - self.user.RemainingTokens())/self.user.status['refillRate'] - (60000 - self.user.status['refillIn'])/60000.0
        if tcomplete < 0.0:
            tcomplete = 1.0
        logging.info('Estimated time to complete {:d} queries is {:.2f} minutes'.format(len(asins), tcomplete))
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

    


        
        