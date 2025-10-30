import numpy as np

# domain codes
# Valid values: [ 1: com | 2: co.uk | 3: de | 4: fr | 5:
#                 co.jp | 6: ca | 7: cn | 8: it | 9: es | 10: in | 11: com.mx | 12: com.br ]
DCODES = ["RESERVED", "US", "GB", "DE", "FR", "JP", "CA", "CN", "IT", "ES", "IN", "MX", "BR"]

# Status code dictionary/key
SCODES = {
    "400": "REQUEST_REJECTED",
    "402": "PAYMENT_REQUIRED",
    "405": "METHOD_NOT_ALLOWED",
    "429": "NOT_ENOUGH_TOKEN",
}

# hardcoded ordinal time from
KEEPA_ST_ORDINAL = np.datetime64("2011-01-01")
