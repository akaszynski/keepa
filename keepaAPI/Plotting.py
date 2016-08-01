# -*- coding: utf-8 -*-
"""
Plotting module product data returned from keepa interface module

"""

# Check if matplotlib is installed
try:
    import matplotlib
except:
    raise Exception('matplotlib module unavailable.\nPlease run install matplotlib to use this plotting feature')

# Check python version
import sys
if sys.version_info.major == 3:
    # matplotlib for python3 requires different backend
    try:
        matplotlib.use('Qt5Agg')
    except:
        raise Exception('Please install "python3-pyqt5" for matplotlib in python3 to work')

import matplotlib.pyplot as plt

import numpy as np
from keepaAPI import keepaTime

def PlotProduct(product, keys=[], rng=None):
    """ Plots a product using matplotlib """

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
        
        elif 'SalesRank' in key and not 'time' in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key], product['data'][key][-1]).astype(np.float)
            ReplaceInvalid(y)
            salesax.step(x, y, where='pre')
            saleslegend.append(key)
        
        elif 'Offers' in key and not 'time' in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key], product['data'][key][-1]).astype(np.float)
            ReplaceInvalid(y)
            offerax.step(x, y, where='pre')
            offerlegend.append(key)
            
        elif not 'time' in key:
            x = np.append(product['data'][key + '_time'], lstupdate)
            y = np.append(product['data'][key], product['data'][key][-1]).astype(np.float)
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
#    mask = np.logical_not(np.isnan(arr))
    mask = arr < 0.0
    if mask.any():
        arr[mask] = np.nan
    
