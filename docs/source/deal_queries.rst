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

Async Usage
-----------

.. code-block:: python

   response = await async_api.deals(request, typed=True)
