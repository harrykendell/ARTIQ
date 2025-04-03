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
class Eom(DEVICE):
    """
    A simple class that holds information about an EOM driven by a mirny/almazny

    """

    name: str  # friendly name to access by

    frequency: float  # The mirny frequency
    attenuation: float

    mirny_ch: str
    almazny_ch: str

    mirny_enabled: bool = False
    almazny_enabled: bool = False
