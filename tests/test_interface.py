import pytest
import os
import keepaAPI


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
        request = self.api.ProductQuery(PRODUCT_ASIN, history=False)
        product = request[0]
        assert product['csv'] is None
        assert product['asin'] == PRODUCT_ASIN

# self = TestInterface()
