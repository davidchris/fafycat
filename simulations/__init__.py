"""Financial simulation framework for FafyCat.

This module can be used standalone with DictDataSource or CSVDataSource,
or with FafyCat integration via FafyCatDataLoader.
"""

from . import scenarios, visualizations
from .core import Scenario, Simulation, SimulationResult
from .data_loader import FafyCatDataLoader
from .data_sources import CSVDataSource, DataSource, DictDataSource

__version__ = "0.1.0"
__all__ = [
    # Core simulation classes
    "Scenario",
    "Simulation",
    "SimulationResult",
    # Data sources (abstract + implementations)
    "DataSource",
    "DictDataSource",
    "CSVDataSource",
    "FafyCatDataLoader",
    # Submodules
    "scenarios",
    "visualizations",
]
