Keepa Python Client
*******************

``keepa`` is a synchronous and asynchronous Python client for Keepa's Amazon
product and price-history API.

Get an API key through `Keepa Data Access <https://get.keepa.com/d7vrq>`_.

Install
-------

.. code-block:: console

   pip install keepa

Quick Start
===========

.. code-block:: python

   import keepa

   api = keepa.Keepa("<REAL_KEEPA_KEY>")
   products = api.query("B0088PUEPK")
   print(products[0]["title"])

Dictionary responses remain the default. Pass ``typed=True`` to supported
methods for Pydantic response models with attribute access.

.. code-block:: python

   product = api.query("B0088PUEPK", typed=True)[0]
   print(product.title)

Product Histories
=================

Price and offer histories are returned as timestamped arrays ready for
analysis with NumPy, pandas, or Matplotlib.

.. container:: plot-gallery

   .. figure:: images/Product_Price_Plot.png
      :alt: Amazon product price history with multiple offer conditions

      Product price history

   .. figure:: images/Product_Offer_Plot.png
      :alt: Amazon marketplace offer history over time

      Marketplace offer history

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
