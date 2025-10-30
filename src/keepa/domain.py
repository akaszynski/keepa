from enum import Enum


class Domain(Enum):
    """Enumeration for Amazon domain regions.

    Examples
    --------
    >>> import keepa
    >>> keepa.Domain.US
    <Domain.US: 'US'>

    """

    RESERVED = "RESERVED"
    US = "US"
    GB = "GB"
    DE = "DE"
    FR = "FR"
    JP = "JP"
    CA = "CA"
    RESERVED2 = "RESERVED2"
    IT = "IT"
    ES = "ES"
    IN = "IN"
    MX = "MX"
    BR = "BR"
