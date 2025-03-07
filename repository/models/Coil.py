"""
Models for data structures

These classes define data structures that can be used in other parts of the code
and can optionally implement data validation.

By using `Pydantic <https://docs.pydantic.dev/latest/>`_. dataclasses, these
models act as normal python classes and so are fully compatible with ARTIQ
kernels.
"""

from pydantic.dataclasses import dataclass
from repository.models.Device import DEVICE


@dataclass
class CoilPair(DEVICE):
    """
    A simple class that holds information about a pair of coils driven from the fastino

    """

    coil1: str  # The first voltage driven supply
    coil2: str  # The second voltage driven supply

    default_current_comm: float = None
    default_current_diff: float = None
