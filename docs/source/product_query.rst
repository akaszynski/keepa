Queries
=======
Keepa requests require a paid API key from `Keepa Data Access
<https://get.keepa.com/d7vrq>`_ and consume tokens. The client waits for tokens
by default; use ``wait=False`` only when your application manages token
availability itself.

.. code-block:: python

   import keepa

   api = keepa.Keepa("<REAL_KEEPA_KEY>")

Choose a guide based on the result you need:

* :doc:`product_data` for product metadata and batch queries.
* :doc:`product_history` for price history, sales rank, and named statistics.
* :doc:`offer_queries` for marketplace offers and offer history.
* :doc:`deal_queries` for deal discovery and typed deal responses.
* :doc:`category_queries` for category lookup and best-seller lists.
* :doc:`product_finder` for filtered product discovery.

The synchronous and asynchronous clients accept the same endpoint parameters.
Async calls use ``await`` and return the same response shapes.

.. code-block:: python

   async_api = await keepa.AsyncKeepa.create("<REAL_KEEPA_KEY>")
   products = await async_api.query("B0088PUEPK")

.. toctree::
   :maxdepth: 1
   :hidden:

   product_data
   product_history
   offer_queries
   deal_queries
   category_queries
   product_finder

See :doc:`api_methods` for complete signatures and `Keepa Pricing
<https://get.keepa.com/d7vrq>`_ for current token costs and subscription
options.
