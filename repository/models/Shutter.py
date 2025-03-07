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
class Shutter(DEVICE):
    """
    A simple class that holds information about a Shutter driven by a TTL signal

    """

    name: str  # friendly name to access by

    ttl: str
    delay: float

    enabled: bool = False
