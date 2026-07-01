.. _ref_backend_models:

Typed Backend Models
--------------------
By default, ``keepa`` returns dictionaries so existing code keeps working.
Set ``typed=True`` on supported methods to get permissive Pydantic models
generated from Keepa's backend Java schema.

.. code:: python

    import keepa

    api = keepa.Keepa("<REAL_KEEPA_KEY>")
    products = api.query("B0088PUEPK", typed=True)
    product = products[0]

    print(product.asin)
    print(product.title)

Typed responses support attribute access for known backend fields and keep
unknown future fields instead of rejecting them. Convert a model back to a
dictionary with ``model_dump()``.

.. code:: python

    product_dict = product.model_dump(exclude_none=True)

Nested objects are models as well, so editors and type checkers can follow the
response structure. Pydantic validates input data and reports the complete
field path when a value does not match the backend schema.

.. code:: python

    first_offer = product.offers[0]
    print(first_offer.offerId)

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

Typed responses are currently supported for product queries, category search
and lookup, seller queries, and deals.

.. code:: python

    categories = api.category_lookup(0, typed=True)
    first_category = next(iter(categories.values()))
    print(first_category.name)

    sellers = api.seller_query("A2L77EE7U53NWQ", typed=True)
    print(sellers["A2L77EE7U53NWQ"].sellerName)

    deals = api.deals({"page": 0, "domainId": 1}, typed=True)
    print(deals.dr[0].asin)

The asynchronous client uses the same ``typed=True`` option.

.. code:: python

    import asyncio
    import keepa

    async def main():
        api = await keepa.AsyncKeepa().create("<REAL_KEEPA_KEY>")
        products = await api.query("B0088PUEPK", typed=True)
        return products[0].title

    title = asyncio.run(main())

Typed seller models mirror the raw backend schema. The default dictionary
seller response can convert selected Keepa time fields to Python datetime
values with ``to_datetime=True``; typed sellers leave those fields as the
backend integer values.

The models are regenerated from the pinned backend commit recorded in
``backend_models.BACKEND_COMMIT``. If Keepa adds fields before this library is
updated, typed models still preserve those fields because they allow extra
backend data.
