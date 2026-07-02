.. _ref_backend_models:

Typed Responses
---------------
By default, ``keepa`` returns dictionaries so existing code keeps working.
Set ``typed=True`` on supported methods to get permissive Pydantic models
generated from Keepa's backend Java schema. The option changes only the
response representation; request parameters and token costs are unchanged.

.. code:: python

    import keepa

    api = keepa.Keepa("<REAL_KEEPA_KEY>")
    products = api.query("B0088PUEPK", typed=True)
    product = products[0]

    print(product.asin)
    print(product.title)

Return Shapes
~~~~~~~~~~~~~
The sync and async clients expose the same typed response shapes.

===================================  ==========================================
Method                               Return value with ``typed=True``
===================================  ==========================================
``query``                            ``list[``:class:`keepa.models.backend.Product`\ ``]``
``search_for_categories``            ``dict[str,`` :class:`keepa.models.backend.Category`\ ``]``
``category_lookup``                  ``dict[str,`` :class:`keepa.models.backend.Category`\ ``]``
``best_sellers_query``               :class:`keepa.models.backend.BestSellers`
``seller_query``                     ``dict[str,`` :class:`keepa.models.backend.Seller`\ ``]``
``deals``                            :class:`keepa.models.backend.DealResponse`
===================================  ==========================================

Fields are optional because Keepa omits fields based on the endpoint,
request parameters, product type, and data availability. Check optional
containers before indexing them.

.. code:: python

    if product.offers:
        first_offer = product.offers[0]
        if first_offer is not None:
            print(first_offer.offerId)

Nested backend objects are models as well, so editors and type checkers can
follow the response structure. Pydantic validates known fields and reports the
complete field path when a value does not match the backend schema. Unknown
fields are retained to remain forward-compatible with backend additions.

Serialization
~~~~~~~~~~~~~
Use ``model_dump()`` for a regular Python dictionary. Pass ``exclude_none=True``
to omit unavailable backend fields and ``by_alias=True`` to preserve exact
backend field names for aliased Python identifiers.

.. code:: python

    product_dict = product.model_dump(exclude_none=True, by_alias=True)

Product History and Stats
~~~~~~~~~~~~~~~~~~~~~~~~~
Product queries still perform the library's normal history and statistics
parsing in typed mode. When Keepa returns history for ``history=True``, parsed
NumPy arrays are available through ``product.data``. When requested statistics
are available, ``product.stats_parsed`` contains their parsed values. These
attributes are omitted when their source data is unavailable. They are
client-generated conveniences rather than backend schema fields, so they are
retained as extra model attributes.

.. code:: python

    products = api.query("B0088PUEPK", history=True, stats=90, typed=True)
    product = products[0]
    history = getattr(product, "data", {})
    new_prices = history.get("NEW")

    stats = getattr(product, "stats_parsed", {})
    current_amazon_price = stats.get("current", {}).get("AMAZON")

Model Discovery
~~~~~~~~~~~~~~~

Every request and response structure from the pinned backend schema is
available as a model, including structures that are not returned directly by
the high-level client. Use Pydantic's schema API to inspect a complete output
shape programmatically.

.. code:: python

    product_schema = keepa.backend_models.Product.model_json_schema()
    print(product_schema["properties"]["offers"])

The generated models are available from ``keepa.backend_models`` and
``keepa.models.backend``.

.. code:: python

    from keepa import backend_models

    assert isinstance(product, backend_models.Product)
    print(backend_models.BACKEND_COMMIT)

``backend_models.__all__`` lists every generated model and enum at the pinned
commit. This is useful for schema tooling that needs to inspect the entire
backend surface rather than one response type.

.. code:: python

    available_models = backend_models.__all__

See :doc:`backend_model_reference` for an individual API page for every
generated model and enum.

.. toctree::
   :hidden:

   backend_model_reference

Other Endpoints
~~~~~~~~~~~~~~~

.. code:: python

    categories = api.category_lookup(0, typed=True)
    first_category = next(iter(categories.values()))
    print(first_category.name)

    best_sellers = api.best_sellers_query("402283011", typed=True)
    print(best_sellers.asinList[:10])

    sellers = api.seller_query("A2L77EE7U53NWQ", typed=True)
    print(sellers["A2L77EE7U53NWQ"].sellerName)

    deals = api.deals({"page": 0, "domainId": 1}, typed=True)
    deal_asins = [deal.asin for deal in deals.dr or [] if deal is not None]

The asynchronous client uses the same ``typed=True`` option.

.. code:: python

    import asyncio

    async def main():
        api = await keepa.AsyncKeepa.create("<REAL_KEEPA_KEY>")
        products = await api.query("B0088PUEPK", typed=True)
        return products[0].title

    title = asyncio.run(main())

Typed seller models mirror the raw backend schema. The default dictionary
seller response can convert selected Keepa time fields to Python datetime
values with ``to_datetime=True``; typed sellers leave those fields as the
backend integer values.

On the synchronous client, ``raw=True`` returns HTTP responses and cannot be
combined with ``typed=True``. The asynchronous client does not support raw
HTTP responses.

The models are regenerated from the pinned backend commit recorded in
``backend_models.BACKEND_COMMIT``. If Keepa adds fields before this library is
updated, typed models still preserve those fields because they allow extra
backend data.
