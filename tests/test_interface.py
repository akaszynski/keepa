import datetime
from itertools import chain
import os
import warnings

import numpy as np
import pandas as pd
import pytest
import requests

import keepa
from keepa import keepa_minutes_to_time

# reduce the request limit for testing

keepa.interface.REQLIM = 2

path = os.path.dirname(os.path.realpath(__file__))
keyfile = os.path.join(path, "key")
weak_keyfile = os.path.join(path, "weak_key")

if os.path.isfile(keyfile):
    with open(keyfile) as f:
        TESTINGKEY = f.read()
    with open(weak_keyfile) as f:
        WEAKTESTINGKEY = f.read()
else:
    # from travis-ci or appveyor
    TESTINGKEY = os.environ["KEEPAKEY"]
    WEAKTESTINGKEY = os.environ["WEAKKEEPAKEY"]

# Dead Man's Hand (The Unorthodox Chronicles)
# just need an active product with a buybox
PRODUCT_ASIN = "0593440412"
HARD_DRIVE_PRODUCT_ASIN = "B0088PUEPK"
VIDEO_ASIN = "B0060CU5DE"

# ASINs of a bunch of chairs generated with
# categories = API.search_for_categories('chairs')
# asins = []
# for category in categories:
#     asins.extend(API.best_sellers_query(category))
# PRODUCT_ASINS = asins[:40]


PRODUCT_ASINS = [
    "B00IAPNWG6",
    "B01CUJMSB2",
    "B01CUJMRLI",
    "B00BMPT7CE",
    "B00IAPNWE8",
    "B0127O51FK",
    "B01CUJMT3E",
    "B01A5ZIXKI",
    "B00KQPBF1W",
    "B000J3UZ58",
    "B00196LLDO",
    "B002VWK2EE",
    "B00E2I3BPM",
    "B004FRSUO2",
    "B00CM1TJ1G",
    "B00VS4514C",
    "B075G1B1PK",
    "B00R9EAH8U",
    "B004L2JKTU",
    "B008SIDW2E",
    "B078XL8CCW",
    "B000VXII46",
    "B07D1CJ8CK",
    "B07B5HZ7D9",
    "B002VWK2EO",
    "B000VXII5A",
    "B004N1AA5W",
    "B002VWKP3W",
    "B00CM9OM0G",
    "B002VWKP4G",
    "B004N18JDC",
    "B07MDHF4CP",
    "B002VWKP3C",
    "B07FTVSNL2",
    "B002VWKP5A",
    "B002O0LBFW",
    "B07BM1Q64Q",
    "B004N18JM8",
    "B004N1AA02",
    "B002VWK2EY",
]


# open connection to keepa
@pytest.fixture(scope="module")
def api():
    keepa_api = keepa.Keepa(TESTINGKEY)
    assert keepa_api.tokens_left
    assert keepa_api.time_to_refill >= 0
    return keepa_api


def test_deals(api):
    deal_parms = {
        "page": 0,
        "domainId": 1,
        "excludeCategories": [1064954, 11091801],
        "includeCategories": [16310101],
    }
    deals = api.deals(deal_parms)
    assert isinstance(deals, dict)
    assert isinstance(deals["dr"], list)


def test_invalidkey():
    with pytest.raises(Exception):
        keepa.Api("thisisnotavalidkey")


def test_deadkey():
    with pytest.raises(Exception):
        # this key returns "payment required"
        deadkey = "8ueigrvvnsp5too0atlb5f11veinerkud47p686ekr7vgr9qtj1t1tle15fffkkm"
        keepa.Api(deadkey)


def test_product_finder_categories(api):
    product_parms = {"categories_include": ["1055398"]}
    products = api.product_finder(product_parms)
    assert products


def test_product_finder_query(api: keepa.Keepa) -> None:
    """Test product finder and ensure perPage overrides n_products."""
    per_page_n_products = 50
    product_parms = {
        "author": "jim butcher",
        "page": 1,
        "perPage": per_page_n_products,
        "categories_exclude": ["1055398"],
    }
    asins = api.product_finder(product_parms, n_products=100)
    assert asins
    assert len(asins) == per_page_n_products


# def test_throttling(api):
#     api = keepa.Keepa(WEAKTESTINGKEY)
#     keepa.interface.REQLIM = 20

#     # exhaust tokens
#     while api.tokens_left > 0:
#         api.query(PRODUCT_ASINS[:5])

#     # this must trigger a wait...
#     t_start = time.time()
#     products = api.query(PRODUCT_ASINS)
#     assert (time.time() - t_start) > 1
#     keepa.interface.REQLIM = 2


def test_productquery_raw(api):
    request = api.query(PRODUCT_ASIN, history=False, raw=True)
    raw = request[0]
    assert isinstance(raw, requests.Response)
    assert PRODUCT_ASIN in raw.text


def test_productquery_nohistory(api):
    pre_update_tokens = api.tokens_left
    request = api.query(PRODUCT_ASIN, history=False)
    assert api.tokens_left != pre_update_tokens

    product = request[0]
    assert product["csv"] is None
    assert product["asin"] == PRODUCT_ASIN


def test_not_an_asin(api):
    with pytest.raises(Exception):
        asins = ["0000000000", "000000000x"]
        api.query(asins)


def test_isbn13(api):
    isbn13 = "9780786222728"
    api.query(isbn13, product_code_is_asin=False, history=False)


def test_buybox(api: keepa.Keepa) -> None:
    request = api.query(PRODUCT_ASIN, history=True, buybox=True)
    product = request[0]
    assert "BUY_BOX_SHIPPING" in product["data"]


def test_productquery_update(api):
    request = api.query(PRODUCT_ASIN, update=0, stats=90, rating=True)
    product = request[0]

    # should be live data
    now = datetime.datetime.now()
    delta = now - product["data"]["USED_time"][-1]
    assert delta.days <= 60

    # check for empty arrays
    history = product["data"]
    for key in history:
        if isinstance(history[key], pd.DataFrame):
            assert history[key].any().value
        else:
            assert history[key].any()

        # should be a key pair
        if "time" not in key and key[:3] != "df_":
            assert history[key].size == history[key + "_time"].size

    # check for stats
    assert "stats" in product

    # no offers requested by default
    assert product["offers"] is None


def test_productquery_offers(api):
    request = api.query(PRODUCT_ASIN, offers=20)
    product = request[0]

    offers = product["offers"]
    for offer in offers:
        assert offer["lastSeen"]
        assert not len(offer["offerCSV"]) % 3

    # also test offer conversion
    offer = offers[1]
    times, prices = keepa.convert_offer_history(offer["offerCSV"])
    assert times.dtype == datetime.datetime
    assert prices.dtype == np.double
    assert len(times)
    assert len(prices)


def test_productquery_only_live_offers(api):
    """Tests that no historical offer data was returned from response if only_live_offers param was specified."""
    max_offers = 20
    request = api.query(PRODUCT_ASIN, offers=max_offers, only_live_offers=True, history=False)

    # there may not be any offers
    product_offers = request[0]["offers"]
    if product_offers is not None:
        # All offers are live and have similar times
        last_seen_values = [offer["lastSeen"] for offer in product_offers]
        assert np.diff(np.abs(last_seen_values)).mean() < 60 * 24  # within one day
    else:
        warnings.warn(f"No live offers for {PRODUCT_ASIN}")


def test_productquery_days(api, max_days: int = 5):
    """Tests that 'days' param limits historical data to X days.

    This includes the csv, buyBoxSellerIdHistory, salesRanks, offers and
    offers.offerCSV fields.  Each field may contain one day which seems out of
    specified range. This means the value of the field has been unchanged since
    that date, and was still active at least until the max_days cutoff.
    """

    request = api.query(PRODUCT_ASIN, days=max_days, history=True, offers=20)
    product = request[0]

    def convert(minutes):
        """Convert keepaminutes to time."""
        times = {keepa_minutes_to_time(keepa_minute).date() for keepa_minute in minutes}
        return list(times)

    # Converting each field's list of keepa minutes into flat list of unique days.
    sales_ranks = convert(chain.from_iterable(product["salesRanks"].values()))[0::2]
    offers = convert(offer["lastSeen"] for offer in product["offers"])
    buy_box_seller_id_history = convert(product["buyBoxSellerIdHistory"][0::2])
    offers_csv = list(convert(offer["offerCSV"][0::3]) for offer in product["offers"])
    df_dates = list(
        list(df.axes[0]) for df_name, df in product["data"].items() if "df_" in df_name and any(df)
    )
    df_dates = list(
        list(datetime.date(year=ts.year, month=ts.month, day=ts.day) for ts in stamps)
        for stamps in df_dates
    )

    # Check for out of range days.
    today = datetime.date.today()

    def is_out_of_range(d):
        return (today - d).days > max_days

    for field_days in [
        sales_ranks,
        offers,
        buy_box_seller_id_history,
        *df_dates,
        *offers_csv,
    ]:
        field_days.sort()

        # let oldest day be out of range
        field_days = field_days[1:] if is_out_of_range(field_days[0]) else field_days
        for day in field_days:
            if is_out_of_range(day):
                warnings.warn(f'Day "{day}" is older than {max_days} from today')


def test_productquery_offers_invalid(api):
    with pytest.raises(ValueError):
        api.query(PRODUCT_ASIN, offers=2000)


def test_productquery_offers_multiple(api):
    products = api.query(PRODUCT_ASINS)

    asins = np.unique([product["asin"] for product in products])
    assert len(asins) == len(PRODUCT_ASINS)
    assert np.isin(asins, PRODUCT_ASINS).all()


def test_domain(api):
    asin = "0394800028"
    request = api.query(asin, history=False, domain="BR")
    product = request[0]
    assert product["asin"] == asin


def test_invalid_domain(api):
    with pytest.raises(ValueError):
        api.query(PRODUCT_ASIN, history=False, domain="XX")


def test_bestsellers(api):
    categories = api.search_for_categories("chairs")
    category = list(categories.items())[0][0]
    asins = api.best_sellers_query(category)
    valid_asins = keepa.format_items(asins)
    assert len(asins) == valid_asins.size


@pytest.mark.xfail  # will fail if not run in a while due to timeout
def test_buybox_used(api):
    request = api.query(HARD_DRIVE_PRODUCT_ASIN, history=True, offers=20)
    df = keepa.process_used_buybox(request[0]["buyBoxUsedHistory"])
    assert isinstance(df, pd.DataFrame)


def test_categories(api):
    categories = api.search_for_categories("chairs")
    catids = list(categories.keys())
    for catid in catids:
        assert "chairs" in categories[catid]["name"].lower()


def test_categorylookup(api):
    categories = api.category_lookup(0)
    for cat_id in categories:
        assert categories[cat_id]["name"]


def test_invalid_category(api):
    with pytest.raises(Exception):
        api.category_lookup(-1)


def test_stock(api):
    request = api.query(PRODUCT_ASIN, history=False, stock=True, offers=20)

    # all live offers must have stock
    product = request[0]
    assert product["offersSuccessful"]
    live = product["liveOffersOrder"]
    if live is not None:
        for offer in product["offers"]:
            if offer["offerId"] in live:
                if "stockCSV" in offer:
                    if not offer["stockCSV"][-1]:
                        warnings.warn(f"No live offers for {PRODUCT_ASIN}")
    else:
        warnings.warn(f"No live offers for {PRODUCT_ASIN}")


def test_keepatime(api):
    keepa_st_ordinal = datetime.datetime(2011, 1, 1)
    assert keepa_st_ordinal == keepa.keepa_minutes_to_time(0)
    assert keepa.keepa_minutes_to_time(0, to_datetime=False)


def test_plotting(api):
    request = api.query(PRODUCT_ASIN, history=True)
    product = request[0]
    keepa.plot_product(product, show=False)


def test_empty(api):
    import matplotlib.pyplot as plt

    plt.close("all")
    products = api.query(["B01I6KT07E", "B01G5BJHVK", "B017LJP1MO"])
    with pytest.raises(Exception):
        keepa.plot_product(products[0], show=False)


def test_seller_query(api):
    seller_id = "A2L77EE7U53NWQ"
    seller_info = api.seller_query(seller_id)
    assert len(seller_info) == 1
    assert seller_id in seller_info


def test_seller_query_list(api):
    seller_id = ["A2L77EE7U53NWQ", "AMMEOJ0MXANX1"]
    seller_info = api.seller_query(seller_id)
    assert len(seller_info) == len(seller_id)
    assert set(seller_info).issubset(seller_id)


def test_seller_query_long_list(api):
    seller_id = ["A2L77EE7U53NWQ"] * 200
    with pytest.raises(RuntimeError):
        api.seller_query(seller_id)


def test_video_query(api: keepa.Keepa) -> None:
    """Test if the videos query parameter works."""
    response = api.query("B00UFMKSDW", history=False, videos=False)
    product = response[0]
    assert "videos" not in product

    response = api.query("B00UFMKSDW", history=False, videos=True)
    product = response[0]
    assert "videos" in product


def test_aplus(api: keepa.Keepa) -> None:
    product_nominal = api.query("B0DDDD8WD6", history=False, aplus=False)[0]
    assert "aPlus" not in product_nominal
    product_aplus = api.query("B0DDDD8WD6", history=False, aplus=True)[0]
    assert "aPlus" in product_aplus
