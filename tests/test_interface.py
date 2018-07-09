import numpy as np
import pytest
import os
import keepaAPI
import datetime

keyfile = '/home/alex/Books/keepaAPI/tests/key'
if os.path.isfile(keyfile):
    with open(keyfile) as f:
        TESTINGKEY = f.read()
else:
    # from travis-ci
    TESTINGKEY = os.environ.get('KEEPAKEY')

# this key returns "payment required"
DEADKEY = '8ueigrvvnsp5too0atlb5f11veinerkud47p686ekr7vgr9qtj1t1tle15fffkkm'

# yes, it's harry potter
PRODUCT_ASIN = '0439064872'
PRODUCT_ASINS = ['0439064872', '0439136369', '059035342X', '0439139600', '0439358078',
                 '0439785960', '0545139708']

class TestInterface(object):

    # open connection to keepaAPI
    api = keepaAPI.API(TESTINGKEY)
    assert api.user.RemainingTokens()

    def test_invalidkey(self):
        with pytest.raises(Exception):
            keepaAPI.API('thisisnotavalidkey')

    def test_deadkey(self):
        with pytest.raises(Exception):
            keepaAPI.API(DEADKEY)

    def test_productquery_nohistory(self):
        pre_update_tokens = self.api.user.RemainingTokens()
        request = self.api.ProductQuery(PRODUCT_ASIN, history=False)
        assert self.api.user.RemainingTokens() != pre_update_tokens

        product = request[0]
        assert product['csv'] is None
        assert product['asin'] == PRODUCT_ASIN

    def test_productquery_update(self):
        request = self.api.ProductQuery(PRODUCT_ASIN, update=0, stats=90, rating=True)
        product = request[0]

        # should be live data
        now = datetime.datetime.now()
        delta = now - product['data']['USED_time'][-1]
        assert delta.days <= 1

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

    def test_productquery_offers(self):
        request = self.api.ProductQuery(PRODUCT_ASIN, offers=20)
        product = request[0]

        offers = product['offers']
        for offer in offers:
            assert offer['lastSeen']
            assert not len(offer['offerCSV']) % 3

    def test_domain(self):
        request = self.api.ProductQuery(PRODUCT_ASIN, history=False, domain='DE')
        product = request[0]
        assert product['asin'] == PRODUCT_ASIN

    def test_checkasins(self):
        assert not keepaAPI.CheckASINs('notanasin')

    def test_bestsellers(self):
        category = '402333011'
        asins = self.api.BestSellersQuery(category)
        valid_asins = keepaAPI.CheckASINs(asins)
        assert len(asins) == valid_asins.size


    def test_categories(self):
        categories = self.api.SearchForCategories('chairs')
        catids = list(categories.keys())
        for catid in catids:
            assert 'chairs' in categories[catid]['name'].lower()

    def test_categorylookup(self):
        categories = self.api.CategoryLookup(0)
        for catId in categories:
            assert categories[catId]['name']


def test_keepatime():
    keepa_st_ordinal = datetime.datetime(2011, 1, 1)
    assert keepa_st_ordinal == keepaAPI.KeepaMinutesToTime(0)
    assert keepa_st_ordinal == keepaAPI.KeepaMinutesToTime(0, to_datetime=False)
