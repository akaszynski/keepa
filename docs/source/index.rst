keepa Documentation
===================
This Python module allows you to interface with the API at `Keepa <https://keepa.com/>`_ to query for Amazon product information and history.  It also contains a plotting module to allow for plotting of a product.

See API pricing at `Keepa API <https://keepa.com/#!api>`_

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   product_query
   api_methods

Brief Example
-------------
Here's an example of obtaining a product and plotting its price and offer history:

.. code:: python

    import keepa

    # establish interface with keepa (this is not a real key)
    mykey = '0000000000000000000000000000000000000000000000000000000000000000'
    api = keepa.Keepa(mykey)

    # plot product request 
    request = 'B0088PUEPK'
    products = api.query(request)
    product = products[0]
    keepa.plot_product(product)

.. figure:: ./images/Product_Price_Plot.png
    :width: 500pt

    Product Price Plot

.. figure:: ./images/Product_Offer_Plot.png
    :width: 500pt

    Product Offers Plot

Installation
------------
``keepa`` can be installed from PyPi using

.. code::

    pip install keepa --user

Source code can also be downloaded from `GitHub <https://github.com/akaszynski/keepa>`_ and installed using:

.. code::

   python setup.py install


Acknowledgments
---------------
This Python code written by Alex Kaszynski is based on Java code written by Marius Johann, CEO keepa. Java source is can be found at `keepa <https://github.com/keepacom/api_backend/>`_.


License
-------
Apache License, please see license file. Work is credited to both Alex Kaszynski and Marius Johann.


Indices and tables
==================
* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
