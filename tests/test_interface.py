import time
import sys
import os

import numpy as np
import pytest

import keepa
import datetime

py2 = sys.version_info.major == 2


# slow down number of offers for testing
keepa.interface.REQLIM = 2

try:
    path = os.path.dirname(os.path.realpath(__file__))
    keyfile = os.path.join(path, 'key')
    weak_keyfile = os.path.join(path, 'weak_key')
except:
    keyfile = '/home/alex/books/keepa/tests/key'
    weak_keyfile = '/home/alex/books/keepa/tests/weak_key'

if os.path.isfile(keyfile):
    with open(keyfile) as f:
        TESTINGKEY = f.read()
    with open(weak_keyfile) as f:
        WEAKTESTINGKEY = f.read()
else:
    # from travis-ci or appveyor
    TESTINGKEY = os.environ.get('KEEPAKEY')
    WEAKTESTINGKEY = os.environ.get('WEAKKEEPAKEY')


# this key returns "payment required"
DEADKEY = '8ueigrvvnsp5too0atlb5f11veinerkud47p686ekr7vgr9qtj1t1tle15fffkkm'


# harry potter book ISBN
PRODUCT_ASIN = '0439064872'
PRODUCT_ASINS = ['0439064872', '0439136369', '059035342X',
                 '0439139600', '0439358078', '0439785960',
                 '0545139708']

# CHAIRS = ['1465049797', '8873932029', '9178893003', 'B00002N84F',
#           'B00004YO3X', 'B00006IDEA', 'B000078CRW', 'B00009YUI8']

# open connection to keepa
API = keepa.Keepa(TESTINGKEY)
assert API.tokens_left
assert API.time_to_refill >= 0


def test_invalidkey():
    with pytest.raises(Exception):
        keepa.Api('thisisnotavalidkey')


def test_deadkey():
    with pytest.raises(Exception):
        keepa.Api(DEADKEY)


def test_throttling():
    api = keepa.Keepa(WEAKTESTINGKEY)
    keepa.interface.REQLIM = 20

    # exaust tokens
    while api.tokens_left > 0:
        api.query(PRODUCT_ASINS)

    # this must trigger a wait...
    t_start = time.time()
    api.query(PRODUCT_ASINS)
    t_end = time.time()
    assert (t_end - t_start) > 30

    keepa.interface.REQLIM = 2


def test_productquery_nohistory():
    pre_update_tokens = API.tokens_left
    request = API.query(PRODUCT_ASIN, history=False)
    assert API.tokens_left != pre_update_tokens

    product = request[0]
    assert product['csv'] is None
    assert product['asin'] == PRODUCT_ASIN


def test_not_an_asin():
    with pytest.raises(Exception):
        asins = ['0000000000', '000000000x']
        request = API.query(asins)

def test_isbn13():
    isbn13 = '9780786222728'
    request = API.query(isbn13, product_code_is_asin=False, history=False)


def test_productquery_update():
    request = API.query(PRODUCT_ASIN, update=0, stats=90, rating=True)
    product = request[0]

    # should be live data
    now = datetime.datetime.now()
    delta = now - product['data']['USED_time'][-1]
    assert delta.days <= 30

    # check for empty arrays
    history = product['data']
    for key in history:
        assert history[key].any()

        # should be a key pair
        if 'time' not in key:
            assert history[key].size == history[key + '_time'].size

    # check for stats
    assert 'stats' in product

    # no offers requested by default
    assert product['offers'] is None


def test_productquery_offers():
    request = API.query(PRODUCT_ASIN, offers=20)
    product = request[0]

    offers = product['offers']
    for offer in offers:
        assert offer['lastSeen']
        assert not len(offer['offerCSV']) % 3

    # also test offer conversion
    offer = offers[1]
    times, prices = keepa.convert_offer_history(offer['offerCSV'])
    assert times.dtype == datetime.datetime
    assert prices.dtype == np.double
    assert len(times)
    assert len(prices)


def test_productquery_offers_invalid():
    with pytest.raises(ValueError):
        request = API.query(PRODUCT_ASIN, offers=2000)


def test_productquery_offers_multiple():
    products = API.query(PRODUCT_ASINS)

    asins = np.unique([product['asin'] for product in products])
    assert len(asins) == len(PRODUCT_ASINS)
    assert np.in1d(asins, PRODUCT_ASINS).all()


def test_domain():
    request = API.query(PRODUCT_ASIN, history=False, domain='DE')
    product = request[0]
    assert product['asin'] == PRODUCT_ASIN


def test_invalid_domain():
    with pytest.raises(ValueError):
        request = API.query(PRODUCT_ASIN, history=False, domain='XX')


def test_bestsellers():
    category = '402333011'
    asins = API.best_sellers_query(category)
    valid_asins = keepa.format_items(asins)
    assert len(asins) == valid_asins.size


def test_categories():
    categories = API.search_for_categories('chairs')
    catids = list(categories.keys())
    for catid in catids:
        assert 'chairs' in categories[catid]['name'].lower()


def test_categorylookup():
    categories = API.category_lookup(0)
    for cat_id in categories:
        assert categories[cat_id]['name']


def test_invalid_category():
    with pytest.raises(Exception):
        API.category_lookup(-1)


def test_stock():
    request = API.query(PRODUCT_ASIN, history=False, stock=True,
                        offers=20)

    # all live offers must have stock
    product = request[0]
    assert product['offersSuccessful']
    live = product['liveOffersOrder']
    for offer in product['offers']:
        if offer['offerId'] in live:
            assert offer['stockCSV'][-1]


def test_keepatime():
    keepa_st_ordinal = datetime.datetime(2011, 1, 1)
    assert keepa_st_ordinal == keepa.keepa_minutes_to_time(0)
    assert keepa.keepa_minutes_to_time(0, to_datetime=False)


@pytest.mark.skipif(py2, reason="Requires python 3.5+ for testing")
def test_plotting():
    request = API.query(PRODUCT_ASIN, history=True)
    product = request[0]
    keepa.plot_product(product, show=False)


@pytest.mark.skipif(py2, reason="Requires python 3.5+ for testing")
def test_empty():
    import matplotlib.pyplot as plt
    plt.close('all')
    products = API.query(['B01I6KT07E', 'B01G5BJHVK', 'B017LJP1MO'])
    with pytest.raises(Exception):
        keepa.plot_product(products[0], show=False)


def test_seller_query():
    seller_id = 'A2L77EE7U53NWQ'
    seller_info = API.seller_query(seller_id)
    assert len(seller_info) == 1
    assert seller_id in seller_info
    

def test_seller_query_list():
    seller_id = ['A2L77EE7U53NWQ', 'AMMEOJ0MXANX1']
    seller_info = API.seller_query(seller_id)
    assert len(seller_info) == len(seller_id)
    assert set(seller_info).issubset(seller_id)


def test_seller_query_long_list():
    seller_id = ['A2L77EE7U53NWQ']*200
    with pytest.raises(RuntimeError):
        seller_info = API.seller_query(seller_id)
