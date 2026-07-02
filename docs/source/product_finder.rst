Product Finder
==============
``product_finder`` searches Keepa's product database and returns ASINs. It does
not return full product objects; pass the ASINs to ``query`` when product data
is needed.

Basic Search
------------

.. code-block:: python

   parameters = {
       "author": "jim butcher",
       "sort": ["current_SALES", "asc"],
       "perPage": 100,
   }
   asins = api.product_finder(parameters)

Validated Parameters
--------------------
:class:`keepa.ProductParams` validates backend field names before a request
consumes tokens. Unknown names raise a validation error.

.. code-block:: python

   parameters = keepa.ProductParams(
       author="jim butcher",
       sort=["current_SALES", "asc"],
       perPage=100,
   )
   asins = api.product_finder(parameters)

The generated backend :class:`keepa.models.backend.ProductFinderRequest` model
is accepted too. Use it when you want a request object that mirrors the pinned
backend schema exactly.

.. code-block:: python

   request = keepa.backend_models.ProductFinderRequest(
       author=["jim butcher"],
       current_SALES_lte=50000,
   )
   asins = api.product_finder(request)

The backend exposes more than a thousand filters. Inspect them through
``ProductParams.model_fields``,
``ProductParams.model_json_schema()``, or
``keepa.backend_models.ProductFinderRequest.model_json_schema()``.

Result Limits and Pages
-----------------------
``n_products`` sets ``perPage`` only when the supplied parameters do not
already define it. An explicit ``perPage`` therefore takes precedence.

.. code-block:: python

   first_page = keepa.ProductParams(
       categories_include=["2619533011"],
       current_SALES_lte=50000,
       page=0,
       perPage=200,
   )
   asins = api.product_finder(first_page)

Increment ``page`` for additional backend pages. Keepa limits deep pagination;
use selective filters and a stable sort for large result sets.

Fetch Product Data
------------------

.. code-block:: python

   asins = api.product_finder(parameters)
   products = api.query(asins, history=False)

Async Usage
-----------

.. code-block:: python

   asins = await async_api.product_finder(parameters)
