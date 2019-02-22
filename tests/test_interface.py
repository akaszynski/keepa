import numpy as np
import pytest
import os
import keepa
import datetime

# slow down number of offers for testing
keepa.interface.REQLIM = 2

try:
    path = os.path.dirname(os.path.realpath(__file__))
    keyfile = os.path.join(key)
except:
    keyfile = '/home/alex/books/keepa/tests/key'

if os.path.isfile(keyfile):
    with open(keyfile) as f:
        TESTINGKEY = f.read()
else:
    # from travis-ci or appveyor
    TESTINGKEY = os.environ.get('KEEPAKEY')


# this key returns "payment required"
DEADKEY = '8ueigrvvnsp5too0atlb5f11veinerkud47p686ekr7vgr9qtj1t1tle15fffkkm'


# harry potter book ISBN
PRODUCT_ASIN = '0439064872'
PRODUCT_ASINS = ['0439064872', '0439136369', '059035342X',
                 '0439139600', '0439358078', '0439785960',
                 '0545139708']


# open connection to keepa
api = keepa.Keepa(TESTINGKEY)
assert api.user.tokens_left
assert api.user.time_to_refill >= 0

def test_invalidkey():
    with pytest.raises(Exception):
        keepa.API('thisisnotavalidkey')


def test_deadkey():
    with pytest.raises(Exception):
        keepa.API(DEADKEY)


def test_productquery_nohistory():
    pre_update_tokens = api.user.tokens_left
    request = api.query(PRODUCT_ASIN, history=False)
    assert api.user.tokens_left != pre_update_tokens

    product = request[0]
    assert product['csv'] is None
    assert product['asin'] == PRODUCT_ASIN


def test_not_an_asin():
    with pytest.raises(Exception):
        asins = ['0000000000', '000000000x']
        request = api.query(asins)

def test_isbn13():
    isbn13 = '9780786222728'
    request = api.query(isbn13, product_code_is_asin=False, history=False)


def test_productquery_update():
    request = api.query(PRODUCT_ASIN, update=0, stats=90, rating=True)
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
    request = api.query(PRODUCT_ASIN, offers=20)
    product = request[0]

    offers = product['offers']
    for offer in offers:
        assert offer['lastSeen']
        assert not len(offer['offerCSV']) % 3


def test_productquery_offers_invalid():
    with pytest.raises(ValueError):
        request = api.query(PRODUCT_ASIN, offers=2000)


def test_productquery_offers_multiple():
    products = api.query(PRODUCT_ASINS)

    asins = np.unique([product['asin'] for product in products])
    assert len(asins) == len(PRODUCT_ASINS)
    assert np.in1d(asins, PRODUCT_ASINS).all()


def test_domain():
    request = api.query(PRODUCT_ASIN, history=False, domain='DE')
    product = request[0]
    assert product['asin'] == PRODUCT_ASIN


def test_invalid_domain():
    with pytest.raises(ValueError):
        request = api.query(PRODUCT_ASIN, history=False, domain='XX')


def test_bestsellers():
    category = '402333011'
    asins = api.best_sellers_query(category)
    valid_asins = keepa.format_items(asins)
    assert len(asins) == valid_asins.size


def test_categories():
    categories = api.search_for_categories('chairs')
    catids = list(categories.keys())
    for catid in catids:
        assert 'chairs' in categories[catid]['name'].lower()


def test_categorylookup():
    categories = api.category_lookup(0)
    for cat_id in categories:
        assert categories[cat_id]['name']


def test_invalid_category():
    with pytest.raises(Exception):
        api.category_lookup(-1)


def test_stock():
    request = api.query(PRODUCT_ASIN, history=False,
                               stock=True, offers=20)

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
