Category and Best-Seller Queries
================================
Use category search for matching names, category lookup for exact IDs and
root categories, and best-seller queries for ranked ASIN lists.

Search Categories
-----------------

.. code-block:: python

   categories = api.search_for_categories("chairs")
   for category_id, category in list(categories.items())[:5]:
       print(category_id, category["name"])

Search results are dictionaries keyed by category ID. Pass ``typed=True`` to
receive ``Category`` model values instead.

Root and Parent Categories
--------------------------
Look up category ID ``0`` to retrieve root categories. Set
``include_parents=True`` when an exact category lookup should include its
parent chain.

.. code-block:: python

   roots = api.category_lookup(0)
   category = api.category_lookup(402283011, include_parents=True)

Best Sellers
------------
``best_sellers_query`` returns an ordered list of ASINs for a category by
default. Pass ``typed=True`` to receive the full ``BestSellers`` backend model,
including metadata such as ``domainId``, ``categoryId``, and ``lastUpdate``
when Keepa includes it.

.. code-block:: python

   asins = api.best_sellers_query("402283011")
   print(asins[:10])

   best_sellers = api.best_sellers_query("402283011", typed=True)
   print(best_sellers.asinList[:10])

The ``rank_avg_range`` option accepts ``0``, ``30``, ``90``, or ``180``.
Use ``variations=True`` to retain variations and ``sublist=True`` to request
sub-category-rank ordering.

Async Usage
-----------

.. code-block:: python

   categories = await async_api.search_for_categories("chairs", typed=True)
   best_sellers = await async_api.best_sellers_query("402283011", typed=True)
