Queries
=======
Keepa requests require a paid API key from `Keepa Data Access
<https://get.keepa.com/d7vrq>`_ and consume tokens. The client waits for tokens
by default; use ``wait=False`` only when your application manages token
availability itself.

Timeouts and Token Use
======================
``Keepa(accesskey, timeout=...)`` controls how long the client waits for the
backend to send a response; it is not a total runtime limit for a large batch.
The client chunks product queries into backend-sized requests, but token cost
is calculated by Keepa and can be more than one token per ASIN when options
such as ``offers``, ``stock``, ``buybox``, ``rating``, ``stats``, or forced
updates are enabled.

For large batches, keep ``wait=True``, use smaller chunks when debugging, and
inspect ``api.tokens_left`` or ``api.status`` between calls. If a request is
timing out, reduce expensive options first and then increase ``timeout`` only
when the backend legitimately needs longer to produce the requested data.

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
