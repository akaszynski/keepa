"""Interface module to download Amazon product and history data from keepa.com."""

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from typing import Any, Optional, Union

import aiohttp
from tqdm import tqdm

from keepa.constants import SCODES
from keepa.data_models import ProductParams
from keepa.domain import Domain
from keepa.keepa_sync import Keepa
from keepa.query_keys import DEAL_REQUEST_KEYS
from keepa.utils import (
    _domain_to_dcode,
    _parse_seller,
    _parse_stats,
    format_items,
    is_documented_by,
    parse_csv,
)

log = logging.getLogger(__name__)

# Request limit
REQUEST_LIMIT = 100


class AsyncKeepa:
    r"""Class to support an asynchronous Python interface to keepa server.

    Initializes API with access key.  Access key can be obtained by
    signing up for a reoccurring or one time plan at:
    https://keepa.com/#!api

    Parameters
    ----------
    accesskey : str
        64 character access key string.

    timeout : float, optional
        Default timeout when issuing any request.  This is not a time
        limit on the entire response download; rather, an exception is
        raised if the server has not issued a response for timeout
        seconds.  Setting this to 0 disables the timeout, but will
        cause any request to hang indefiantly should keepa.com be down

    Examples
    --------
    Query for all of Jim Butcher's books using the asynchronous
    ``keepa.AsyncKeepa`` class.

    >>> import asyncio
    >>> import keepa
    >>> product_parms = {"author": "jim butcher"}
    >>> async def main():
    ...     key = "<REAL_KEEPA_KEY>"
    ...     api = await keepa.AsyncKeepa().create(key)
    ...     return await api.product_finder(product_parms)
    ...
    >>> asins = asyncio.run(main())
    >>> asins
    ['B000HRMAR2',
     '0578799790',
     'B07PW1SVHM',
    ...
     'B003MXM744',
     '0133235750',
     'B01MXXLJPZ']

    Query for product with ASIN ``'B0088PUEPK'`` using the asynchronous
    keepa interface.

    >>> import asyncio
    >>> import keepa
    >>> async def main():
    ...     key = "<REAL_KEEPA_KEY>"
    ...     api = await keepa.AsyncKeepa().create(key)
    ...     return await api.query("B0088PUEPK")
    ...
    >>> response = asyncio.run(main())
    >>> response[0]["title"]
    'Western Digital 1TB WD Blue PC Internal Hard Drive HDD - 7200 RPM,
    SATA 6 Gb/s, 64 MB Cache, 3.5" - WD10EZEX'

    """

    accesskey: str
    tokens_left: int
    _timeout: float

    @classmethod
    async def create(cls, accesskey: str, timeout: float = 10):
        """Create the async object."""
        self = AsyncKeepa()
        self.accesskey = accesskey
        self.tokens_left = 0
        self._timeout = timeout

        # don't update the user status on init
        self.status = {"tokensLeft": None, "refillIn": None, "refillRate": None, "timestamp": None}
        return self

    @property
    def time_to_refill(self):
        """Return the time to refill in seconds."""
        # Get current timestamp in milliseconds from UNIX epoch
        now = int(time.time() * 1000)
        timeatrefile = self.status["timestamp"] + self.status["refillIn"]

        # wait plus one second fudge factor
        timetorefil = timeatrefile - now + 1000
        if timetorefil < 0:
            timetorefil = 0

        # Account for negative tokens left
        if self.tokens_left < 0:
            timetorefil += (abs(self.tokens_left) / self.status["refillRate"]) * 60000

        # Return value in seconds
        return timetorefil / 1000.0

    async def update_status(self):
        """Update available tokens."""
        self.status = await self._request("token", {"key": self.accesskey}, wait=False)

    async def wait_for_tokens(self):
        """Check if there are any remaining tokens and waits if none are available."""
        await self.update_status()

        # Wait if no tokens available
        if self.tokens_left <= 0:
            tdelay = self.time_to_refill
            log.warning("Waiting %.0f seconds for additional tokens", tdelay)
            await asyncio.sleep(tdelay)
            await self.update_status()

    @is_documented_by(Keepa.query)
    async def query(
        self,
        items: Union[str, Sequence[str]],
        stats: Optional[int] = None,
        domain: str = "US",
        history: bool = True,
        offers: Optional[int] = None,
        update: Optional[int] = None,
        to_datetime: bool = True,
        rating: bool = False,
        out_of_stock_as_nan: bool = True,
        stock: bool = False,
        product_code_is_asin: bool = True,
        progress_bar: bool = True,
        buybox: bool = False,
        wait: bool = True,
        days: Optional[int] = None,
        only_live_offers: Optional[bool] = None,
        raw: bool = False,
        videos: bool = False,
        aplus: bool = False,
        extra_params: dict[str, Any] = {},
    ):
        """Documented in Keepa.query."""
        if raw:
            raise ValueError("Raw response is only available in the non-async class")

        # Format items into numpy array
        try:
            items = format_items(items)
        except BaseException:
            raise Exception("Invalid product codes input")
        assert len(items), "No valid product codes"

        nitems = len(items)
        if nitems == 1:
            log.debug("Executing single product query")
        else:
            log.debug("Executing %d item product query", nitems)

        # check offer input
        if offers:
            if not isinstance(offers, int):
                raise TypeError('Parameter "offers" must be an interger')

            if offers > 100 or offers < 20:
                raise ValueError('Parameter "offers" must be between 20 and 100')

        # Report time to completion
        if self.status["refillRate"] is not None:
            tcomplete = (
                float(nitems - self.tokens_left) / self.status["refillRate"]
                - (60000 - self.status["refillIn"]) / 60000.0
            )
            if tcomplete < 0.0:
                tcomplete = 0.5
            log.debug(
                "Estimated time to complete %d request(s) is %.2f minutes",
                nitems,
                tcomplete,
            )
            log.debug("\twith a refill rate of %d token(s) per minute", self.status["refillRate"])

        # product list
        products = []

        pbar = None
        if progress_bar:
            pbar = tqdm(total=nitems)

        # Number of requests is dependent on the number of items and
        # request limit.  Use available tokens first
        idx = 0  # or number complete
        while idx < nitems:
            nrequest = nitems - idx

            # cap request
            if nrequest > REQUEST_LIMIT:
                nrequest = REQUEST_LIMIT

            # request from keepa and increment current position
            item_request = items[idx : idx + nrequest]  # noqa: E203
            response = await self._product_query(
                item_request,
                product_code_is_asin,
                stats=stats,
                domain=domain,
                stock=stock,
                offers=offers,
                update=update,
                history=history,
                rating=rating,
                to_datetime=to_datetime,
                out_of_stock_as_nan=out_of_stock_as_nan,
                buybox=buybox,
                wait=wait,
                days=days,
                only_live_offers=only_live_offers,
                videos=videos,
                aplus=aplus,
                **extra_params,
            )
            idx += nrequest
            products.extend(response["products"])

            if pbar is not None:
                pbar.update(nrequest)

        return products

    @is_documented_by(Keepa._product_query)
    async def _product_query(self, items, product_code_is_asin=True, **kwargs):
        """Documented in Keepa._product_query."""
        # ASINs convert to comma joined string
        assert len(items) <= 100

        if product_code_is_asin:
            kwargs["asin"] = ",".join(items)
        else:
            kwargs["code"] = ",".join(items)

        kwargs["key"] = self.accesskey
        kwargs["domain"] = _domain_to_dcode(kwargs["domain"])

        # Convert bool values to 0 and 1.
        kwargs["stock"] = int(kwargs["stock"])
        kwargs["history"] = int(kwargs["history"])
        kwargs["rating"] = int(kwargs["rating"])
        kwargs["buybox"] = int(kwargs["buybox"])

        if kwargs["update"] is None:
            del kwargs["update"]
        else:
            kwargs["update"] = int(kwargs["update"])

        if kwargs["offers"] is None:
            del kwargs["offers"]
        else:
            kwargs["offers"] = int(kwargs["offers"])

        if kwargs["only_live_offers"] is None:
            del kwargs["only_live_offers"]
        else:
            kwargs["only-live-offers"] = int(kwargs.pop("only_live_offers"))
            # Keepa's param actually doesn't use snake_case.
            # Keeping with snake case for consistency

        if kwargs["days"] is None:
            del kwargs["days"]
        else:
            assert kwargs["days"] > 0

        if kwargs["stats"] is None:
            del kwargs["stats"]

        # videos and aplus must be ints
        kwargs["videos"] = int(kwargs["videos"])
        kwargs["aplus"] = int(kwargs["aplus"])

        out_of_stock_as_nan = kwargs.pop("out_of_stock_as_nan", True)
        to_datetime = kwargs.pop("to_datetime", True)

        # Query and replace csv with parsed data if history enabled
        wait = kwargs.get("wait")
        kwargs.pop("wait", None)

        raw_response = kwargs.pop("raw", False)
        response = await self._request("product", kwargs, wait=wait, raw_response=raw_response)
        if kwargs["history"]:
            if "products" not in response:
                raise RuntimeError("No products in response. Possibly invalid ASINs")

            for product in response["products"]:
                if product["csv"]:  # if data exists
                    product["data"] = parse_csv(product["csv"], to_datetime, out_of_stock_as_nan)

        if kwargs.get("stats", None):
            for product in response["products"]:
                stats = product.get("stats", None)
                if stats:
                    product["stats_parsed"] = _parse_stats(stats, to_datetime)

        return response

    @is_documented_by(Keepa.best_sellers_query)
    async def best_sellers_query(
        self, category, rank_avg_range=0, domain: Union[str, Domain] = "US", wait=True
    ):
        """Documented by Keepa.best_sellers_query."""
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "category": category,
            "range": rank_avg_range,
        }

        response = await self._request("bestsellers", payload, wait=wait)
        if "bestSellersList" in response:
            return response["bestSellersList"]["asinList"]
        else:  # pragma: no cover
            log.info("Best sellers search results not yet available")

    @is_documented_by(Keepa.search_for_categories)
    async def search_for_categories(self, searchterm, domain: Union[str, Domain] = "US", wait=True):
        """Documented by Keepa.search_for_categories."""
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "type": "category",
            "term": searchterm,
        }

        response = await self._request("search", payload, wait=wait)
        if response["categories"] == {}:  # pragma no cover
            raise Exception(
                "Categories search results not yet available " + "or no search terms found."
            )
        else:
            return response["categories"]

    @is_documented_by(Keepa.category_lookup)
    async def category_lookup(
        self, category_id, domain: Union[str, Domain] = "US", include_parents=0, wait=True
    ):
        """Documented by Keepa.category_lookup."""
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "category": category_id,
            "parents": include_parents,
        }

        response = await self._request("category", payload, wait=wait)
        if response["categories"] == {}:  # pragma no cover
            raise Exception("Category lookup results not yet available or no" + "match found.")
        else:
            return response["categories"]

    @is_documented_by(Keepa.seller_query)
    async def seller_query(
        self,
        seller_id,
        domain: Union[str, Domain] = "US",
        to_datetime=True,
        storefront=False,
        update=None,
        wait=True,
    ):
        """Documented by Keepa.sellerer_query."""
        if isinstance(seller_id, list):
            if len(seller_id) > 100:
                err_str = "seller_id can contain at maximum 100 sellers"
                raise RuntimeError(err_str)
            seller = ",".join(seller_id)
        else:
            seller = seller_id

        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "seller": seller,
        }

        if storefront:
            payload["storefront"] = int(storefront)
        if update:
            payload["update"] = update

        response = await self._request("seller", payload, wait=wait)
        return _parse_seller(response["sellers"], to_datetime)

    @is_documented_by(Keepa.product_finder)
    async def product_finder(
        self,
        product_parms: Union[dict[str, Any], ProductParams],
        domain: Union[str, Domain] = "US",
        wait: bool = True,
        n_products: int = 50,
    ) -> list[str]:
        """Documented by Keepa.product_finder."""
        if isinstance(product_parms, dict):
            product_parms_valid = ProductParams(**product_parms)
        else:
            product_parms_valid = product_parms
        product_parms_dict = product_parms_valid.model_dump(exclude_none=True)
        product_parms_dict.setdefault("perPage", n_products)
        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "selection": json.dumps(product_parms_dict),
        }

        response = await self._request("query", payload, wait=wait)
        return response["asinList"]

    @is_documented_by(Keepa.deals)
    async def deals(self, deal_parms, domain: Union[str, Domain] = "US", wait=True):
        """Documented in Keepa.deals."""
        # verify valid keys
        for key in deal_parms:
            if key not in DEAL_REQUEST_KEYS:
                raise ValueError(f'Invalid key "{key}"')

            # verify json type
            key_type = DEAL_REQUEST_KEYS[key]
            deal_parms[key] = key_type(deal_parms[key])

        deal_parms.setdefault("priceTypes", 0)

        payload = {
            "key": self.accesskey,
            "domain": _domain_to_dcode(domain),
            "selection": json.dumps(deal_parms),
        }

        deals = await self._request("deal", payload, wait=wait)
        return deals["deals"]

    async def _request(self, request_type, payload, wait: bool = True, raw_response: bool = False):
        """Documented in Keepa._request."""
        while True:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.keepa.com/{request_type}/?",
                    params=payload,
                    timeout=self._timeout,
                ) as raw:
                    status_code = str(raw.status)

                    try:
                        response = await raw.json()
                    except Exception:
                        raise RuntimeError(f"Invalid JSON from Keepa API (status {status_code})")

                    # user status is always returned
                    if "tokensLeft" in response:
                        self.tokens_left = response["tokensLeft"]
                        self.status["tokensLeft"] = self.tokens_left
                        log.info("%d tokens remain", self.tokens_left)
                    for key in ["refillIn", "refillRate", "timestamp"]:
                        if key in response:
                            self.status[key] = response[key]

                    if status_code == "200":
                        if raw_response:
                            return raw
                        return response

                    if status_code == "429" and wait:
                        tdelay = self.time_to_refill
                        log.warning("Waiting %.0f seconds for additional tokens", tdelay)
                        time.sleep(tdelay)
                        continue

                    # otherwise, it's an error code
                    if status_code in SCODES:
                        raise RuntimeError(SCODES[status_code])
                    raise RuntimeError(f"REQUEST_FAILED. Status code: {status_code}")
