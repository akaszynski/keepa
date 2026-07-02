Deal Queries
============
``deals`` returns recently changed products that match deal filters. Dictionary
requests and responses remain the default, while generated Pydantic models are
available for users who want structured request construction and typed output.

Basic Deal Search
-----------------

.. code-block:: python

   parameters = {
       "page": 0,
       "domainId": 1,
       "includeCategories": [16310101],
       "priceTypes": [0],
   }
   deals = api.deals(parameters)
   first_asin = deals["dr"][0]["asin"]

Typed Request and Response
--------------------------
Use :class:`keepa.models.backend.DealRequest` to construct the request and
``typed=True`` to receive a :class:`keepa.models.backend.DealResponse`.

.. code-block:: python

   request = keepa.backend_models.DealRequest(
       page=0,
       domainId=1,
       includeCategories=[16310101],
       priceTypes=[0],
   )
   response = api.deals(request, typed=True)
   asins = [deal.asin for deal in response.dr or [] if deal is not None]

Deal Deltas and Previous Values
-------------------------------
Deal arrays such as ``current``, ``delta``, ``deltaPercent``, and
``deltaLast`` are indexed by Keepa's product CSV type order. Use
``keepa.csv_indices`` to map a price type name to the array position.

.. code-block:: python

   deal = response.dr[0]
   csv_index = next(index for index, name, _ in keepa.csv_indices if name == "NEW")

   current_new = deal.current[csv_index]
   change_from_last = deal.deltaLast[csv_index]
   previous_new = current_new - change_from_last

Only compute a previous value when both array entries are present and Keepa
supplies a signed delta for that price type. Keepa uses sentinel values such
as ``-1`` for unavailable prices, so filter those values before arithmetic.

Async Usage
-----------

.. code-block:: python

   response = await async_api.deals(request, typed=True)
