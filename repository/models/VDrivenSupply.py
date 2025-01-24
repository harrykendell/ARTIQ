"""
Models for data structures

These classes define data structures that can be used in other parts of the code
and can optionally implement data validation.

By using `Pydantic <https://docs.pydantic.dev/latest/>`_. dataclasses, these
models act as normal python classes and so are fully compatible with ARTIQ
kernels.
"""

import logging
from pydantic.dataclasses import dataclass
from artiq.experiment import HasEnvironment


@dataclass
class VDrivenSupply:
    """
    A simple class that holds information about a beam to be controlled via a
    SUServo.

    """

    name: str  # friendly name to access by

    fastino: str
    ch: int

    gain: float  # The Current gain in Amps/Volt
    enabled: bool = False

    def from_dataset(hasEnv: HasEnvironment, name: str):
        # initialise the class with the data from the dataset
        try:
            data = hasEnv.get_dataset("VDrivenSupply." + name)
        except KeyError:
            logging.error(f"Could not find dataset {"VDrivenSupply."+name}")
            raise
        return VDrivenSupply(name=name, **data)

    def to_dataset(self, hasEnv: HasEnvironment):
        # update the dataset with the current class values
        data = {
            n: getattr(self, n)
            for n in self.__dataclass_fields__
            if getattr(self, n) is not None
        }
        hasEnv.set_dataset(
            "VDrivenSupply." + self.name,
            data,
            persist=True,
            broadcast=True,
        )
