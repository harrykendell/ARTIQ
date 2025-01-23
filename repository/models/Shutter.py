"""
Models for data structures

These classes define data structures that can be used in other parts of the code
and can optionally implement data validation.

By using `Pydantic <https://docs.pydantic.dev/latest/>`_. dataclasses, these
models act as normal python classes and so are fully compatible with ARTIQ
kernels.
"""

import logging
from artiq.experiment import HasEnvironment
from pydantic.dataclasses import dataclass


@dataclass
class Shutter:
    """
    A simple class that holds information about a beam to be controlled via a
    SUServo.

    """

    name: str  # friendly name to access by

    ttl: str
    delay: float

    enabled: bool = False

    def from_dataset(hasEnv: HasEnvironment, name: str):
        # initialise the class with the data from the dataset
        try:
            data = hasEnv.get_dataset("Shutter." + name)
        except KeyError:
            logging.error(f"Could not find dataset {'Shutter.'+name}")
            raise
        return Shutter(name=name, **data)

    def to_dataset(self, hasEnv: HasEnvironment):
        # update the dataset with the current class values
        data = {
            n: getattr(self, n)
            for n in self.__dataclass_fields__
            if getattr(self, n) is not None
        }
        hasEnv.set_dataset(
            "Shutter." + self.name,
            data,
            persist=True,
            broadcast=True,
        )
