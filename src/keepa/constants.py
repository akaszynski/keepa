"""Constants for Keepa API interactions."""

import numpy as np

# hardcoded ordinal time from
KEEPA_ST_ORDINAL = np.datetime64("2011-01-01")

# Request limit
REQUEST_LIMIT = 100

# Status code dictionary/key
SCODES = {
    "400": "REQUEST_REJECTED",
    "402": "PAYMENT_REQUIRED",
    "405": "METHOD_NOT_ALLOWED",
    "429": "NOT_ENOUGH_TOKEN",
}

# domain codes
# Valid values: [ 1: com | 2: co.uk | 3: de | 4: fr | 5:
#                 co.jp | 6: ca | 7: cn | 8: it | 9: es | 10: in | 11: com.mx | 12: com.br ]
DCODES = [
    "RESERVED",
    "US",
    "GB",
    "DE",
    "FR",
    "JP",
    "CA",
    "CN",
    "IT",
    "ES",
    "IN",
    "MX",
    "BR",
]
# developer note: appears like CN (China) has changed to RESERVED2

# csv indices. used when parsing csv and stats fields.
# https://github.com/keepacom/api_backend
# see api_backend/src/main/java/com/keepa/api/backend/structs/Product.java
# [index in csv, key name, isfloat(is price or rating)]
csv_indices: list[tuple[int, str, bool]] = [
    (0, "AMAZON", True),
    (1, "NEW", True),
    (2, "USED", True),
    (3, "SALES", False),
    (4, "LISTPRICE", True),
    (5, "COLLECTIBLE", True),
    (6, "REFURBISHED", True),
    (7, "NEW_FBM_SHIPPING", True),
    (8, "LIGHTNING_DEAL", True),
    (9, "WAREHOUSE", True),
    (10, "NEW_FBA", True),
    (11, "COUNT_NEW", False),
    (12, "COUNT_USED", False),
    (13, "COUNT_REFURBISHED", False),
    (14, "CollectableOffers", False),
    (15, "EXTRA_INFO_UPDATES", False),
    (16, "RATING", True),
    (17, "COUNT_REVIEWS", False),
    (18, "BUY_BOX_SHIPPING", True),
    (19, "USED_NEW_SHIPPING", True),
    (20, "USED_VERY_GOOD_SHIPPING", True),
    (21, "USED_GOOD_SHIPPING", True),
    (22, "USED_ACCEPTABLE_SHIPPING", True),
    (23, "COLLECTIBLE_NEW_SHIPPING", True),
    (24, "COLLECTIBLE_VERY_GOOD_SHIPPING", True),
    (25, "COLLECTIBLE_GOOD_SHIPPING", True),
    (26, "COLLECTIBLE_ACCEPTABLE_SHIPPING", True),
    (27, "REFURBISHED_SHIPPING", True),
    (28, "EBAY_NEW_SHIPPING", True),
    (29, "EBAY_USED_SHIPPING", True),
    (30, "TRADE_IN", True),
    (31, "RENT", False),
]

_SELLER_TIME_DATA_KEYS = ["trackedSince", "lastUpdate"]
