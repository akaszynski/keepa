Python keepa Client Library
===========================

.. image:: https://img.shields.io/pypi/v/keepa.svg?logo=python&logoColor=white
   :target: https://pypi.org/project/keepa/

.. image:: https://github.com/akaszynski/keepa/actions/workflows/testing-and-deployment.yml/badge.svg
    :target: https://github.com/akaszynski/keepa/actions/workflows/testing-and-deployment.yml

.. image:: https://readthedocs.org/projects/keepaapi/badge/?version=latest
    :target: https://keepaapi.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

.. image:: https://codecov.io/gh/akaszynski/keepa/branch/main/graph/badge.svg
  :target: https://codecov.io/gh/akaszynski/keepa

.. image:: https://app.codacy.com/project/badge/Grade/9452f99f297c4a6eac14e2d21189ab6f
  :target: https://www.codacy.com/gh/akaszynski/keepa/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=akaszynski/keepa&amp;utm_campaign=Badge_Grade


This Python library allows you to interface with the API at `Keepa
<https://keepa.com/>`_ to query for Amazon product information and
history.  It also contains a plotting module to allow for plotting of
a product.

See API pricing at `Keepa API <https://keepa.com/#!api>`_.

Documentation can be found on readthedocs at `keepa Documentation <https://keepaapi.readthedocs.io/en/latest/>`_.


Requirements
------------
This library is compatible with Python >= 3.8 and requires:

- ``numpy``
- ``aiohttp``
- ``matplotlib``
- ``tqdm``

Product history can be plotted from the raw data when ``matplotlib``
is installed.

Interfacing with the ``keepa`` requires an access key and a monthly
subscription from `Keepa API <https://keepa.com/#!api>`_.

Installation
------------
Module can be installed from `PyPi <https://pypi.org/project/keepa/>`_ with:

.. code::

    pip install keepa


Source code can also be downloaded from `GitHub
<https://github.com/akaszynski/keepa>`_ and installed using::

  cd keepa
  pip install .


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

.. figure:: https://github.com/akaszynski/keepa/raw/main/docs/source/images/Product_Price_Plot.png
    :width: 500pt

    Product Price Plot

.. figure:: https://github.com/akaszynski/keepa/raw/main/docs/source/images/Product_Offer_Plot.png
    :width: 500pt

    Product Offers Plot


Brief Example using async
-------------------------
Here's an example of obtaining a product and plotting its price and
offer history using the ``keepa.AsyncKeepa`` class:

.. code:: python

    >>> import asyncio
    >>> import keepa
    >>> product_parms = {'author': 'jim butcher'}
    >>> async def main():
    ...     key = '<REAL_KEEPA_KEY>'
    ...     api = await keepa.AsyncKeepa().create(key)
    ...     return await api.product_finder(product_parms)
    >>> asins = asyncio.run(main())
    >>> asins
    ['B000HRMAR2',
     '0578799790',
     'B07PW1SVHM',
    ...
     'B003MXM744',
     '0133235750',
     'B01MXXLJPZ']

Query for product with ASIN ``'B0088PUEPK'`` using the asynchronous
keepa interface.

.. code:: python

    >>> import asyncio
    >>> import keepa
    >>> async def main():
    ...     key = '<REAL_KEEPA_KEY>'
    ...     api = await keepa.AsyncKeepa().create(key)
    ...     return await api.query('B0088PUEPK')
    >>> response = asyncio.run(main())
    >>> response[0]['title']
    'Western Digital 1TB WD Blue PC Internal Hard Drive HDD - 7200 RPM,
    SATA 6 Gb/s, 64 MB Cache, 3.5" - WD10EZEX'


Detailed Examples
-----------------
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
``wait=False`` arguments.

.. code:: python

    products = await api.query('059035342X', wait=False)


Buy Box Statistics
~~~~~~~~~~~~~~~~~~
To load used buy box statistics, you have to enable ``offers``. This example
loads in product offers and converts the buy box data into a
``pandas.DataFrame``.

.. code:: pycon

    >>> import keepa
    >>> key = '<REAL_KEEPA_KEY>'
    >>> api = keepa.Keepa(key)
    >>> response = api.query('B0088PUEPK', offers=20)
    >>> product = response[0]
    >>> buybox_info = product['buyBoxUsedHistory']
    >>> df = keepa.process_used_buybox(buybox_info)
                   datetime         user_id         condition  isFBA
    0   2022-11-02 16:46:00  A1QUAC68EAM09F   Used - Like New   True
    1   2022-11-13 10:36:00  A18WXU4I7YR6UA  Used - Very Good  False
    2   2022-11-15 23:50:00   AYUGEV9WZ4X5O   Used - Like New  False
    3   2022-11-17 06:16:00  A18WXU4I7YR6UA  Used - Very Good  False
    4   2022-11-17 10:56:00   AYUGEV9WZ4X5O   Used - Like New  False
    ..                  ...             ...               ...    ...
    115 2023-10-23 10:00:00   AYUGEV9WZ4X5O   Used - Like New  False
    116 2023-10-25 21:14:00  A1U9HDFCZO1A84   Used - Like New  False
    117 2023-10-26 04:08:00   AYUGEV9WZ4X5O   Used - Like New  False
    118 2023-10-27 08:14:00  A1U9HDFCZO1A84   Used - Like New  False
    119 2023-10-27 12:34:00   AYUGEV9WZ4X5O   Used - Like New  False

Contributing
------------
Contribute to this repository by forking this repository and installing in
development mode with::

  git clone https://github.com/<USERNAME>/keepa
  pip install -e .[test]

You can then add your feature or commit your bug fix and then run your unit
testing with::

  pytest

Unit testing will automatically enforce minimum code coverage standards.

Next, to ensure your code meets minimum code styling standards, run::

  pre-commit run --all-files

Finally, `create a pull request`_ from your fork and I'll be sure to review it.


Credits
-------
This Python module, written by Alex Kaszynski and several contribitors, is
based on Java code written by Marius Johann, CEO Keepa. Java source is can be
found at `keepacom/api_backend <https://github.com/keepacom/api_backend/>`_.


License
-------
Apache License, please see license file. Work is credited to both Alex
Kaszynski and Marius Johann.


.. _create a pull request: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request
