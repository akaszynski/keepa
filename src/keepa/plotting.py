"""Plotting module product data returned from keepa interface module."""

import numpy as np

from keepa.interface import keepa_minutes_to_time, parse_csv


def plot_product(
    product, keys=["AMAZON", "USED", "COUNT_USED", "SALES"], price_limit=1000, show=True
):
    """Plot a product using matplotlib.

    Parameters
    ----------
    product : list
        Single product from keepa.query

    keys : list, optional
        Keys to plot.  Defaults to ``['AMAZON', 'USED', 'COUNT_USED', 'SALES']``.

    price_limit : float, optional
        Prices over this value will not be plotted.  Used to ignore
        extreme prices.

    show : bool, optional
        Show plot.

    """
    try:
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover
        raise Exception('Plotting not available.  Please install "matplotlib"')

    if "data" not in product:
        product["data"] = parse_csv[product["csv"]]

    # Use all keys if not specified
    if not keys:
        keys = product["data"].keys()

    # Create three figures, one for price data, offers, and sales rank
    pricefig, priceax = plt.subplots(figsize=(10, 5))
    pricefig.canvas.manager.set_window_title("Product Price Plot")
    plt.title(product["title"])
    plt.xlabel("Date")
    plt.ylabel("Price")
    pricelegend = []

    offerfig, offerax = plt.subplots(figsize=(10, 5))
    offerfig.canvas.manager.set_window_title("Product Offer Plot")
    plt.title(product["title"])
    plt.xlabel("Date")
    plt.ylabel("Listings")
    offerlegend = []

    salesfig, salesax = plt.subplots(figsize=(10, 5))
    salesfig.canvas.manager.set_window_title("Product Sales Rank Plot")
    plt.title(product["title"])
    plt.xlabel("Date")
    plt.ylabel("Sales Rank")
    saleslegend = []

    # Add in last update time
    lstupdate = keepa_minutes_to_time(product["lastUpdate"])

    # Attempt to plot each key
    for key in keys:
        # Continue if key does not exist
        if key not in product["data"]:
            continue

        elif "SALES" in key and "time" not in key:
            if product["data"][key].size > 1:
                x = np.append(product["data"][key + "_time"], lstupdate)
                y = np.append(product["data"][key], product["data"][key][-1]).astype(float)
                replace_invalid(y)

                if np.all(np.isnan(y)):
                    continue

                salesax.step(x, y, where="pre")
                saleslegend.append(key)

        elif "COUNT_" in key and "time" not in key:
            x = np.append(product["data"][key + "_time"], lstupdate)
            y = np.append(product["data"][key], product["data"][key][-1]).astype(float)
            replace_invalid(y)

            if np.all(np.isnan(y)):
                continue

            offerax.step(x, y, where="pre")
            offerlegend.append(key)

        elif "time" not in key:
            x = np.append(product["data"][key + "_time"], lstupdate)
            y = np.append(product["data"][key], product["data"][key][-1]).astype(float)
            replace_invalid(y, max_value=price_limit)

            if np.all(np.isnan(y)):
                continue

            priceax.step(x, y, where="pre")
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

    if not plt.get_fignums():
        raise Exception("Nothing to plot")

    if show:
        plt.show(block=True)
        plt.draw()


def replace_invalid(arr, max_value=None):
    """Replace invalid data with nan."""
    arr[arr < 0.0] = np.nan
    if max_value:
        arr[arr > max_value] = np.nan
