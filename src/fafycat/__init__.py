"""FafyCat - Family Finance Categorizer.

A local-first transaction categorization tool using machine learning.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fafycat")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"
