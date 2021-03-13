keepa
=====

.. image:: https://img.shields.io/pypi/v/keepa.svg?logo=python&logoColor=white
   :target: https://pypi.org/project/keepa/

.. image:: https://travis-ci.org/akaszynski/keepa.svg?branch=master
    :target: https://travis-ci.org/akaszynski/keepa

.. image:: https://readthedocs.org/projects/keepaapi/badge/?version=latest
    :target: https://keepaapi.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

.. image:: https://codecov.io/gh/akaszynski/keepa/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/akaszynski/keepa

Python module to interface to `Keepa <https://keepa.com/>`_ to query for Amazon product information and history.

Documentation can be found on readthedocs at `keepa Documentation <https://keepaapi.readthedocs.io/en/latest/>`_.


Requirements
------------
Module is compatible with Python >= 3.5 . keepa requires:

 - ``numpy``
 - ``aiohttp``
 - ``matplotlib``
 - ``tqdm``

Product history can be plotted from the raw data when ``matplotlib`` is installed.

Interfacing with the ``keepa`` requires an access key and a monthly subscription from `Keepa API <https://keepa.com/#!api>`_


Installation
------------
Module can be installed from PyPi with:

.. code::

    pip install keepa


Source code can also be downloaded from `GitHub <https://github.com/akaszynski/keepa>`_ and installed using ``python setup.py install`` or ``pip install .``


Brief Example
-------------
.. code:: python

    import keepa
    accesskey = 'XXXXXXXXXXXXXXXX' # enter real access key here
    api = keepa.Keepa(accesskey)

    # Single ASIN query
    products = api.query('B0088PUEPK') # returns list of product data

    # Plot result (requires matplotlib)
    keepa.plot_product(products[0])

.. figure:: https://github.com/akaszynski/keepa/raw/master/docs/source/images/Product_Price_Plot.png
    :width: 500pt

    Product Price Plot

.. figure:: https://github.com/akaszynski/keepa/raw/master/docs/source/images/Product_Offer_Plot.png
    :width: 500pt

    Product Offers Plot


Detailed Example
----------------

Import interface and establish connection to server

.. code:: python

    import keepa
    accesskey = 'XXXXXXXXXXXXXXXX' # enter real access key here
    api = keepa.Keepa(accesskey)


Single ASIN query

.. code:: python

    products = api.query('059035342X')

    # See help(api.query) for available options when querying the API


You can use keepa witch async / await too

.. code:: python

    import keepa
    accesskey = 'XXXXXXXXXXXXXXXX' # enter real access key here
    api = await keepa.AsyncKeepa.create(accesskey)


Single ASIN query (async)

.. code:: python

    products = await api.query('059035342X')


Multiple ASIN query from List

.. code:: python

    asins = ['0022841350', '0022841369', '0022841369', '0022841369']
    products = api.query(asins)

Multiple ASIN query from numpy array

.. code:: python

    asins = np.asarray(['0022841350', '0022841369', '0022841369', '0022841369'])
    products = api.query(asins)

Products is a list of product data with one entry per successful result from the Keepa server. Each entry is a dictionary containing the same product data available from `Amazon <http://www.amazon.com>`_.

.. code:: python

    # Available keys
    print(products[0].keys())

    # Print ASIN and title
    print('ASIN is ' + products[0]['asin'])
    print('Title is ' + products[0]['title'])

The raw data is contained within each product result. Raw data is stored as a dictionary with each key paired with its associated time history.

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

    keepa.plot_product(products[0])

You can obtain the offers history for an ASIN (or multiple ASINs) using the ``offers`` parameter.  See the documentation at `Request Products <https://keepa.com/#!discuss/t/request-products/110/1>`_ for further details.

.. code:: python

    products = api.query(asins, offers=20)
    product = products[0]
    offers = product['offers']

    # each offer contains the price history of each offer
    offer = offers[0]
    csv = offer['offerCSV']

    # convert these values to numpy arrays
    times, prices = keepa.convert_offer_history(csv)

    # for a list of active offers, see
    indices = product['liveOffersOrder']

    # with this you can loop through active offers:
    indices = product['liveOffersOrder']
    offer_times = []
    offer_prices = []
    for index in indices:
        csv = offers[index]['offerCSV']
        times, prices = keepa.convert_offer_history(csv)
        offer_times.append(times)
        offer_prices.append(prices)

    # you can aggregate these using np.hstack or plot at the history individually
    import matplotlib.pyplot as plt
    for i in range(len(offer_prices)):
        plt.step(offer_times[i], offer_prices[i])
    plt.show()

If you plan to do a lot of simulatneous query, you might want to speedup query using
`wait=False` arguments.

.. code:: python

    products = await api.query('059035342X', wait=False)

Credits
-------
This Python code, written by Alex Kaszynski, is based on Java code written by Marius Johann, CEO keepa. Java source is can be found at `api_backend <https://github.com/keepacom/api_backend/>`_.


License
-------
Apache License, please see license file. Work is credited to both Alex Kaszynski and Marius Johann.
