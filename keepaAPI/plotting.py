"""
Plotting module product data returned from keepa interface module
"""
import warnings
import numpy as np
from keepaAPI import keepaTime

try:
    import matplotlib.pyplot as plt
    plt_loaded = True
except BaseException as e:
    plt_loaded = False
    warnings.warn('keepaAPI plotting unavailable: %s' % str(e))


def PlotProduct(product, keys=['AMAZON', 'USED', 'COUNT_USED', 'SALES']):
    """
    Plots a product using matplotlib

    Parameters
    ----------
    product : list
        Single product from keepaAPI.ProductQuery

    keys : list, optional
        Keys to plot.  Defaults to ['AMAZON', 'USED', 'COUNT_USED', 'SALES']

    """

    if not plt_loaded:
        raise Exception('Plotting not available.  Check matplotlib install')

    # Use all keys if not specified
    if not keys:
        keys = product['data'].keys()

    # Create three figures, one for price data, offers, and sales rank
    pricefig, priceax = plt.subplots()
    pricefig.canvas.set_window_title('Product Price Plot')
    plt.title(product['title'])
    pricelegend = []

    offerfig, offerax = plt.subplots()
    offerfig.canvas.set_window_title('Product Offer Plot')
    plt.title(product['title'])
    offerlegend = []

    salesfig, salesax = plt.subplots()
    salesfig.canvas.set_window_title('Product Sales Rank Plot')
    plt.title(product['title'])
    saleslegend = []

    # Add in last update time
    lstupdate = keepaTime.KeepaMinutesToTime(product['lastUpdate'])

    # Attempt to plot each key
    for key in keys:

        # Continue if key does not exist
        if key not in product['data'].keys():
            continue

        elif 'SALES' in key and 'time' not in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            ReplaceInvalid(y)
            salesax.step(x, y, where='pre')
            saleslegend.append(key)

        elif 'COUNT_NEW' in key and 'time' not in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            ReplaceInvalid(y)
            offerax.step(x, y, where='pre')
            offerlegend.append(key)

        elif 'COUNT_USED' in key and 'time' not in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            ReplaceInvalid(y)
            offerax.step(x, y, where='pre')
            offerlegend.append(key)

        elif 'time' not in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key],
                          product['data'][key][-1]).astype(np.float)
            ReplaceInvalid(y)
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


def ReplaceInvalid(arr):
    """ Replace invalid data with nan """
    mask = arr < 0.0
    if mask.any():
        arr[mask] = np.nan
