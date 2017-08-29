keepaAPI
========

Python module to interface to `Keepa <https://keepa.com/>`_ to query for Amazon product information and history.

Requirements
------------

Module is compatible with Python 2 and 3. keepaAPI requires:

 - ``numpy``
 - ``requests``

Product history can be plotted from the raw data when ``matplotlib`` is installed.

Interfacing with the ``keepaAPI`` requires an accesskey and a monthly subscription from https://keepa.com/#!api


Installation
------------

Module can be installed from PyPi using ``pip install keepaAPI``

Source code can also be downloaded from `GitHub <https://github.com/akaszynski/keepaAPI>`_ and installed using ``python setup.py install`` or ``pip install .``


Brief Example
-------------

.. code:: python

    import keepaAPI
    accesskey = 'XXXXXXXXXXXXXXXX' # enter real access key here
    api = keepaAPI.API(accesskey)

    # Single ASIN query
    products = api.ProductQuery('059035342X') # returns list of product data

    # Plot result (requires matplotlib)
    keepaAPI.PlotProduct(products[0])


Detailed Example
----------------

Import interface and establish connection to server

.. code:: python

    import keepaAPI
    accesskey = 'XXXXXXXXXXXXXXXX' # enter real access key here
    api = keepaAPI.API(accesskey)

Single ASIN query

.. code:: python

    products = api.ProductQuery('059035342X')

    # See help(api.ProductQuery) for available options when querying the API

Multiple ASIN query from List

.. code:: python

    asins = ['0022841350', '0022841369', '0022841369', '0022841369']
    products = api.ProductQuery(asins)

Multiple ASIN query from numpy array

.. code:: python

    asins = np.asarray(['0022841350', '0022841369', '0022841369', '0022841369'])
    products = api.ProductQuery(asins)

Products is a list of product data with one entry per successful result from the Keepa server. Each entry is a dictionary containing the same product data available from `Amazon <http://www.amazon.com>`_.

.. code:: python

    # Available keys
    print(products[0].keys())

    # Print ASIN and title
    print('ASIN is ' + products[0]['asin'])
    print('Title is ' + products[0]['title'])

The raw data is contained within each product result. Raw data is stored as a dictonary with each key paired with its associated time history.

.. code:: python

    # Access new price history and associated time data
    newprice = products[0]['data']['NEW']
    newpricetime = products[0]['data']['NEW_time']

    # Can be plotted with matplotlib using:
    import matplotlib.pyplot as plt
    plt.step(newpricetime, newprice, where='pre')

    # Keys can be listed by
    print(products[0]['data'].keys())

The product history can also be plotted from the module if ``matplotlib`` is installed

.. code:: python

    keepaAPI.PlotProduct(products[0])


Credits
-------
This Python code, written by Alex Kaszynski, is based on Java code writen by Marius Johann, CEO keepa. Java source is can be found at https://github.com/keepacom/api_backend/


License
-------
Apache License, please see license file. Work is credited to both Alex Kaszynski and Marius
Johann.
