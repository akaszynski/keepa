Keepa Python Client
*******************

``keepa`` is a synchronous and asynchronous Python client for Keepa's Amazon
product, price-history, offer, seller, category, best-seller, product-finder,
and deals API. It is built for analysis workflows: fetch product metadata,
turn Keepa's compact history arrays into Python objects, inspect offers, and
move into pandas, NumPy, or Matplotlib without writing request plumbing.

Get an API key through `Keepa Data Access <https://get.keepa.com/d7vrq>`_.

Install
-------

.. code-block:: console

   pip install keepa

Query Product Data
==================
Start with a product query. Dictionary responses remain the default for
backwards compatibility.

.. code-block:: python

   import keepa

   api = keepa.Keepa("<REAL_KEEPA_KEY>")
   products = api.query("B0088PUEPK", history=True, stats=90)
   product = products[0]

   print(product["title"])
   print(product["stats_parsed"]["current"].get("AMAZON"))

Use ``typed=True`` for generated Pydantic models with editor-friendly
attribute access. Typed responses are planned to become the default in a
future release.

.. code-block:: python

   typed_product = api.query("B0088PUEPK", typed=True)[0]
   print(typed_product.title)
   print(typed_product.asin)

What Comes Back
===============
The high-level methods keep request handling small while returning data at the
right level of detail.

===================================  ==========================================
Method                               Return value
===================================  ==========================================
``query``                            Product dictionaries or
                                      :class:`keepa.models.backend.Product`
                                      models with ``typed=True``.
``deals``                            Deal dictionaries or
                                      :class:`keepa.models.backend.DealResponse`
                                      with ``typed=True``.
``best_sellers_query``               Ranked ASIN lists, or
                                      :class:`keepa.models.backend.BestSellers`
                                      with ``typed=True``.
``category_lookup``                  Categories keyed by category ID.
``search_for_categories``            Matching categories keyed by category ID.
``seller_query``                     Seller dictionaries or
                                      :class:`keepa.models.backend.Seller`
                                      models with ``typed=True``.
``product_finder``                   ASINs matching more than a thousand
                                      product filters.
===================================  ==========================================

Every generated backend model keeps unknown fields, so new backend fields are
preserved even before the Python library is regenerated.

Product Histories
=================

Price and offer histories are returned as timestamped arrays ready for
analysis with NumPy, pandas, or Matplotlib.

.. code-block:: python

   history = product.get("data", {})
   new_prices = history.get("NEW")
   new_times = history.get("NEW_time")

   stats = product.get("stats_parsed", {})
   current_sales_rank = stats.get("current", {}).get("SALES")

.. container:: plot-gallery

   .. figure:: images/Product_Price_Plot.png
      :alt: Amazon product price history with multiple offer conditions

      Product price history

   .. figure:: images/Product_Offer_Plot.png
      :alt: Amazon marketplace offer history over time

      Marketplace offer history

   .. figure:: images/Offer_History.png
      :alt: Active marketplace offer histories

      Active offer histories

Explore the Catalog
===================
Use product finder when you need discovery instead of direct ASIN lookup.
Use category and best-seller queries when category rank matters. Use deals
when you want products that recently changed and match deal filters.

.. code-block:: python

   params = keepa.ProductParams(
       author="jim butcher",
       current_SALES_lte=50_000,
       sort=["current_SALES", "asc"],
       perPage=100,
   )
   asins = api.product_finder(params)
   products = api.query(asins[:10], history=False, typed=True)

.. code-block:: python

   categories = api.search_for_categories("office chairs", typed=True)
   category_id = next(iter(categories))
   best_sellers = api.best_sellers_query(category_id, typed=True)
   print(best_sellers.asinList[:10])

Sync or Async
=============
The synchronous and asynchronous clients expose the same endpoint surface and
typed return shapes.

.. code-block:: python

   async_api = await keepa.AsyncKeepa.create("<REAL_KEEPA_KEY>")
   products = await async_api.query(["B0088PUEPK", "B000HRMAR2"], typed=True)

Next Steps
==========

* :doc:`product_query` explains product history, named statistics, offers,
  categories, and product finder queries.
* :doc:`api_methods` links the synchronous, asynchronous, and shared-type API
  references.
* :doc:`backend_models` documents typed return shapes, serialization, and
  generated model discovery.

.. toctree::
   :maxdepth: 2
   :caption: Contents:
   :hidden:

   product_query
   api_methods
   backend_models
