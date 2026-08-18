"""
Models for data structures

These classes define data structures that can be used in other parts of the code
and can optionally implement data validation.

By using `Pydantic <https://docs.pydantic.dev/latest/>`_. dataclasses, these
models act as normal python classes and so are fully compatible with ARTIQ
kernels.
"""

from numpy import inf
from pydantic.dataclasses import dataclass

from repository.models.Device import DEVICE


@dataclass
class VDrivenSupply(DEVICE):
    """
    A simple class that holds information about a supply driven from the fastino
    It converts the supplied voltage to a the relevant output (current etc.) via gain

    """

    name: str  # friendly name to access by

    fastino: str
    ch: int

    gain: float = 1.0  # The Current gain in Amps/Volt
    min_output: float = 0.0
    max_output: float = inf
    disabled: bool = False
    default_output: float = 0.0
    default_enabled: bool = False

    unit: str = "A"
