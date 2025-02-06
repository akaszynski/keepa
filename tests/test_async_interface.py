import datetime
import os
import warnings

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

import keepa

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

# ASINs of a bunch of chairs
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
@pytest_asyncio.fixture()
async def api():
    keepa_api = await keepa.AsyncKeepa.create(TESTINGKEY)
    assert keepa_api.tokens_left
    assert keepa_api.time_to_refill >= 0
    yield keepa_api


@pytest.mark.asyncio
async def test_deals(api):
    deal_parms = {
        "page": 0,
        "domainId": 1,
        "excludeCategories": [1064954, 11091801],
        "includeCategories": [16310101],
    }
    deals = await api.deals(deal_parms)
    assert isinstance(deals, dict)
    assert isinstance(deals["dr"], list)


@pytest.mark.asyncio
async def test_product_finder_categories(api):
    product_parms = {"categories_include": ["1055398"]}
    products = await api.product_finder(product_parms)
    assert products


@pytest.mark.asyncio
async def test_product_finder_query(api):
    product_parms = {
        "author": "jim butcher",
        "page": 1,
        "perPage": 50,
        "categories_exclude": ["1055398"],
    }
    asins = await api.product_finder(product_parms)
    assert asins

    # using ProductParams
    product_parms = keepa.ProductParams(
        author="jim butcher",
        page=1,
        perPage=50,
        categories_exclude=["1055398"],
    )
    asins = api.product_finder(product_parms)
    assert asins


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


@pytest.mark.asyncio
async def test_productquery_raw(api):
    with pytest.raises(ValueError):
        await api.query(PRODUCT_ASIN, history=False, raw=True)


@pytest.mark.asyncio
async def test_productquery_nohistory(api):
    pre_update_tokens = api.tokens_left
    request = await api.query(PRODUCT_ASIN, history=False)
    assert api.tokens_left != pre_update_tokens

    product = request[0]
    assert product["csv"] is None
    assert product["asin"] == PRODUCT_ASIN


@pytest.mark.asyncio
async def test_not_an_asin(api):
    with pytest.raises(Exception):
        asins = ["0000000000", "000000000x"]
        await api.query(asins)


@pytest.mark.asyncio
async def test_isbn13(api):
    isbn13 = "9780786222728"
    await api.query(isbn13, product_code_is_asin=False, history=False)


@pytest.mark.asyncio
@pytest.mark.xfail  # will fail if not run in a while due to timeout
async def test_buybox(api):
    request = await api.query(PRODUCT_ASIN, history=True, buybox=True)
    product = request[0]
    assert "BUY_BOX_SHIPPING" in product["data"]


@pytest.mark.asyncio
async def test_productquery_update(api):
    request = await api.query(PRODUCT_ASIN, update=0, stats=90, rating=True)
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


@pytest.mark.asyncio
async def test_productquery_offers(api):
    request = await api.query(PRODUCT_ASIN, offers=20)
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


@pytest.mark.asyncio
async def test_productquery_offers_invalid(api):
    with pytest.raises(ValueError):
        await api.query(PRODUCT_ASIN, offers=2000)


@pytest.mark.asyncio
async def test_productquery_offers_multiple(api):
    products = await api.query(PRODUCT_ASINS)

    asins = np.unique([product["asin"] for product in products])
    assert len(asins) == len(PRODUCT_ASINS)
    assert np.isin(asins, PRODUCT_ASINS).all()


@pytest.mark.asyncio
async def test_domain(api):
    request = await api.query(PRODUCT_ASIN, history=False, domain="DE")
    product = request[0]
    assert product["asin"] == PRODUCT_ASIN


@pytest.mark.asyncio
async def test_invalid_domain(api):
    with pytest.raises(ValueError):
        await api.query(PRODUCT_ASIN, history=False, domain="XX")


@pytest.mark.asyncio
async def test_bestsellers(api):
    categories = await api.search_for_categories("chairs")
    category = list(categories.items())[0][0]
    asins = await api.best_sellers_query(category)
    valid_asins = keepa.format_items(asins)
    assert len(asins) == valid_asins.size


@pytest.mark.asyncio
@pytest.mark.xfail  # will fail if not run in a while due to timeout
async def test_buybox_used(api):
    # history must be true to get used buybox
    request = await api.query(HARD_DRIVE_PRODUCT_ASIN, history=True, offers=20)
    df = keepa.process_used_buybox(request[0]["buyBoxUsedHistory"])
    assert isinstance(df, pd.DataFrame)


@pytest.mark.asyncio
async def test_categories(api):
    categories = await api.search_for_categories("chairs")
    catids = list(categories.keys())
    for catid in catids:
        assert "chairs" in categories[catid]["name"].lower()


@pytest.mark.asyncio
async def test_categorylookup(api):
    categories = await api.category_lookup(0)
    for cat_id in categories:
        assert categories[cat_id]["name"]


@pytest.mark.asyncio
async def test_invalid_category(api):
    with pytest.raises(Exception):
        await api.category_lookup(-1)


@pytest.mark.asyncio
async def test_stock(api):
    request = await api.query(PRODUCT_ASIN, history=False, stock=True, offers=20)

    # all live offers should have stock
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


@pytest.mark.asyncio
async def test_keepatime(api):
    keepa_st_ordinal = datetime.datetime(2011, 1, 1)
    assert keepa_st_ordinal == keepa.keepa_minutes_to_time(0)
    assert keepa.keepa_minutes_to_time(0, to_datetime=False)


@pytest.mark.asyncio
async def test_plotting(api):
    request = await api.query(PRODUCT_ASIN, history=True)
    product = request[0]
    keepa.plot_product(product, show=False)


@pytest.mark.asyncio
async def test_empty(api):
    import matplotlib.pyplot as plt

    plt.close("all")
    products = await api.query(["B01I6KT07E", "B01G5BJHVK", "B017LJP1MO"])
    with pytest.raises(Exception):
        keepa.plot_product(products[0], show=False)


@pytest.mark.asyncio
async def test_seller_query(api):
    seller_id = "A2L77EE7U53NWQ"
    seller_info = await api.seller_query(seller_id)
    assert len(seller_info) == 1
    assert seller_id in seller_info


@pytest.mark.asyncio
async def test_seller_query_list(api):
    seller_id = ["A2L77EE7U53NWQ", "AMMEOJ0MXANX1"]
    seller_info = await api.seller_query(seller_id)
    assert len(seller_info) == len(seller_id)
    assert set(seller_info).issubset(seller_id)


@pytest.mark.asyncio
async def test_seller_query_long_list(api):
    seller_id = ["A2L77EE7U53NWQ"] * 200
    with pytest.raises(RuntimeError):
        await api.seller_query(seller_id)
