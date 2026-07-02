Asynchronous Client
-------------------
Create ``AsyncKeepa`` with its asynchronous classmethod, then await endpoint
calls.

.. code:: python

   import keepa

   api = await keepa.AsyncKeepa.create("<REAL_KEEPA_KEY>")
   products = await api.query("B0088PUEPK")

Client
~~~~~~

.. autosummary::
   :toctree: api/async

   keepa.AsyncKeepa

Methods
~~~~~~~

.. autosummary::
   :toctree: api/async

   keepa.AsyncKeepa.best_sellers_query
   keepa.AsyncKeepa.category_lookup
   keepa.AsyncKeepa.create
   keepa.AsyncKeepa.deals
   keepa.AsyncKeepa.download_graph_image
   keepa.AsyncKeepa.product_finder
   keepa.AsyncKeepa.query
   keepa.AsyncKeepa.search_for_categories
   keepa.AsyncKeepa.seller_query
   keepa.AsyncKeepa.update_status
   keepa.AsyncKeepa.wait_for_tokens

Attributes
~~~~~~~~~~

.. autosummary::
   :toctree: api/async

   keepa.AsyncKeepa.time_to_refill
