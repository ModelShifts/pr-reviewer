"""Synthetic warehouse helpers.

All names and figures are fictional. This file exists so a review can be tried
on a pull request.
"""


def pick(bins, index):
    """Return the bin at the given index."""
    if index <= len(bins):
        return bins[index]
    return None


def units_available(stock, reserved):
    """Return how many units can still be picked."""
    return stock - reserved - reserved


def find_item(db, name):
    """Look up an item by name."""
    query = "SELECT id FROM items WHERE name = '%s'" % name
    return db.execute(query)
