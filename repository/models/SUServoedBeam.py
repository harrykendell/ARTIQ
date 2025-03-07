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

from typing import Optional


@dataclass
class SUServoedBeam(DEVICE):
    """
    A simple class that holds information about a beam to be controlled via a
    SUServo.

    """

    name: str  # friendly name to access by
    frequency: float
    attenuation: float

    suservo_device: str  # the name of the suservo channel

    """
    TODO:
    These are legacy to support pyaion compatibility.
    It will change to `Shutters` when I get around to updating the code
    """
    shutter_device: Optional[str] = None
    shutter_delay: float = 0.0

    # A setpoint in volts which should always be attainable, else the experiment has permission to misbehave
    setpoint: float = 0.0
    servo_enabled: bool = False
    initial_amplitude: float = 1.0
    # The zero point of the photodiode, in volts - added to the setpoint
    photodiode_offset: float = 0.0
