"""
Models for data structures

These classes define data structures that can be used in other parts of the code
and can optionally implement data validation.

By using `Pydantic <https://docs.pydantic.dev/latest/>`_. dataclasses, these
models act as normal python classes and so are fully compatible with ARTIQ
kernels.
"""

from typing import Optional
from pydantic.dataclasses import dataclass
from repository.models.Device import DEVICE


@dataclass
class VDrivenSupply(DEVICE):
    """
    A simple class that holds information about a current supply driven from the fastino

    """

    name: str  # friendly name to access by

    fastino: str
    ch: int

    gain: float  # The Current gain in Amps/Volt
    current_limit: float
    enabled: bool = False

    default_current: Optional[float] = None
