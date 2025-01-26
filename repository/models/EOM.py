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
from artiq.language.units import MHz
from pydantic.dataclasses import dataclass


@dataclass
class EOM:
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

    def from_dataset(hasEnv: HasEnvironment, name: str):
        # initialise the class with the data from the dataset
        try:
            data = hasEnv.get_dataset("EOM." + name)
        except KeyError:
            logging.error(f"Could not find dataset {"EOM." +name}")
            raise
        return EOM(name=name, **data)

    def to_dataset(self, hasEnv: HasEnvironment):
        # update the dataset with the current class values

        # get parameters that are not None
        data = self.__dataclass_fields__
        for k, v in data.items():
            if v is None:
                data.pop(k)

        hasEnv.set_dataset(
            "EOM." + self.name,
            data,
            persist=True,
            broadcast=True,
        )
