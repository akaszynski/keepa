Synchronous Client
------------------
``Keepa`` is the synchronous client. Calls block until the API response is
available or the configured timeout is reached.

Client
~~~~~~

.. autosummary::
   :toctree: api/sync

   keepa.Keepa

Methods
~~~~~~~

.. autosummary::
   :toctree: api/sync

   keepa.Keepa.best_sellers_query
   keepa.Keepa.category_lookup
   keepa.Keepa.deals
   keepa.Keepa.download_graph_image
   keepa.Keepa.product_finder
   keepa.Keepa.query
   keepa.Keepa.search_for_categories
   keepa.Keepa.seller_query
   keepa.Keepa.update_status
   keepa.Keepa.wait_for_tokens

Attributes
~~~~~~~~~~

.. autosummary::
   :toctree: api/sync

   keepa.Keepa.time_to_refill
