Product Data
============
``query`` accepts one product code or a sequence. It always returns a list,
including for a single product.

Single Product
--------------

.. code-block:: python

   products = api.query("059035342X", history=False)
   product = products[0]
   print(product["asin"], product.get("title"))

ASIN and ISBN-10 values are accepted by default. Set
``product_code_is_asin=False`` for UPC, EAN, or ISBN-13 values.

.. code-block:: python

   products = api.query("978-0786222728", product_code_is_asin=False)

Batch Queries
-------------
Pass a list, tuple, NumPy array, or other sequence of codes. Results contain
one entry per successful product, so iterate over the returned list rather
than indexing it with an ASIN.

.. code-block:: python

   asins = ["0022841350", "0022841369"]
   products = api.query(asins, history=False)

   for product in products:
       print(product["asin"], product.get("title"))

   products_by_asin = {product["asin"]: product for product in products}

Response Modes
--------------
Dictionary responses remain the default. ``typed=True`` returns generated
Pydantic ``Product`` models without changing request behavior.

.. code-block:: python

   product = api.query("B0088PUEPK", history=False, typed=True)[0]
   print(product.asin, product.title)

The synchronous client also supports ``raw=True`` for unparsed HTTP responses.
``raw=True`` and ``typed=True`` cannot be combined. The asynchronous client
does not expose raw HTTP responses.

Common Options
--------------

``history``
   Include and parse product history. Disable it for metadata-only requests.
``stats``
   Include summary statistics for the requested number of days.
``offers``
   Include marketplace offers. Valid values are 20 through 100 and consume
   additional tokens.
``update``
   Request fresher data from Keepa. This can increase token cost.
``days``
   Limit returned history to the most recent number of days.
``videos`` / ``aplus``
   Include video or A+ content metadata.

See :meth:`keepa.Keepa.query` for the complete parameter reference.
