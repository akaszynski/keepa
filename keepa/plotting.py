"""
Plotting module product data returned from keepa interface module
"""
import datetime
import warnings
import numpy as np
from keepa.interface import keepa_minutes_to_time, parse_csv

try:
    import matplotlib.pyplot as plt
    plt_loaded = True
except BaseException as e:
    plt_loaded = False
    warnings.warn('keepa plotting unavailable: %s' % str(e))


def plot_product(product, keys=['AMAZON', 'USED', 'COUNT_USED', 'SALES'],
                 price_limit=1000):
    """
    Plots a product using matplotlib

    Parameters
    ----------
    product : list
        Single product from keepa.query

    keys : list, optional
        Keys to plot.  Defaults to ['AMAZON', 'USED', 'COUNT_USED', 'SALES']

    price_limit : float, optional
        Prices over this value will not be plotted.  Used to ignore
        extreme prices.

    """
    if not plt_loaded:
        raise Exception('Plotting not available.  Install matplotlib with:\n' +
                        'pip install matplotlib')

    if 'data' not in product:
        product['data'] = parse_csv[product['csv']]

    # Use all keys if not specified
    if not keys:
        keys = product['data'].keys()

    # Create three figures, one for price data, offers, and sales rank
    pricefig, priceax = plt.subplots(figsize=(10, 5))
    pricefig.canvas.set_window_title('Product Price Plot')
    plt.title(product['title'])
    plt.xlabel('Date')
    plt.ylabel('Price')
    pricelegend = []

    offerfig, offerax = plt.subplots(figsize=(10, 5))
    offerfig.canvas.set_window_title('Product Offer Plot')
    plt.title(product['title'])
    plt.xlabel('Date')
    plt.ylabel('Listings')
    offerlegend = []

    salesfig, salesax = plt.subplots(figsize=(10, 5))
    salesfig.canvas.set_window_title('Product Sales Rank Plot')
    plt.title(product['title'])
    plt.xlabel('Date')
    plt.ylabel('Sales Rank')
    saleslegend = []

    # Add in last update time
    lstupdate = keepa_minutes_to_time(product['lastUpdate'])

    # Attempt to plot each key
    for key in keys:
        # Continue if key does not exist
        if key not in product['data']:
            print('%s not in product' % key)
            continue

        elif 'SALES' in key and 'time' not in key:
            if product['data'][key].size == 1:
                print('%s not in product' % key)
                continue
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            replace_invalid(y)
            salesax.step(x, y, where='pre')
            saleslegend.append(key)

        elif 'COUNT_' in key and 'time' not in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            replace_invalid(y)
            offerax.step(x, y, where='pre')
            offerlegend.append(key)

        elif 'time' not in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            replace_invalid(y, max_value=price_limit)
            priceax.step(x, y, where='pre')
            pricelegend.append(key)

    # Add in legends or close figure
    if pricelegend:
        priceax.legend(pricelegend)
    else:
        plt.close(pricefig)

    if offerlegend:
        offerax.legend(offerlegend)
    else:
        plt.close(offerfig)

    if not saleslegend:
        plt.close(salesfig)

    plt.show(block=True)
    plt.draw()


def replace_invalid(arr, max_value=None):
    """ Replace invalid data with nan """
    with np.warnings.catch_warnings():
        np.warnings.filterwarnings('ignore')
        arr[arr < 0.0] = np.nan
        if max_value:
            arr[arr > max_value] = np.nan
