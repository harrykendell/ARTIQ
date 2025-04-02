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

"""
Example usage:

    @dataclass
    class Example(DEVICE):
        some_value: int = 0  # Additional fields specific to Example
        maybe_value: Optional[int] = None # Optional fields

    example = Example(name="my_example", some_value=7)
    example.to_dataset()

    example2 = Example.from_dataset("my_example")
    print(example2.some_value)  # 7
"""


@dataclass
class DEVICE:
    name: str

    @classmethod
    def from_dataset(cls, hasEnv: HasEnvironment, name: str):
        """Initializes the class with the data from the dataset."""
        try:
            data = hasEnv.get_dataset(f"{cls.__name__}.{name}")
        except KeyError:
            logging.error(f"Could not find dataset {cls.__name__}.{name}")
            raise
        return cls(
            name=name, **data
        )  # Dynamically create the correct subclass instance

    def to_dataset(self, hasEnv: HasEnvironment):
        """Updates the dataset with the current class values.
        We skip Optionals that aren't assigned."""
        data = {
            n: getattr(self, n)
            for n in self.__dataclass_fields__
            if getattr(self, n) is not None
        }
        hasEnv.set_dataset(
            f"{self.__class__.__name__}.{self.name}",
            data,
            persist=True,
            broadcast=True,
        )

    def update_from_dataset(self, hasEnv: HasEnvironment):
        """Updates the class values from the dataset."""
        try:
            data = hasEnv.get_dataset(f"{self.__class__.__name__}.{self.name}")
        except KeyError:
            logging.error(
                f"Could not find dataset {self.__class__.__name__}.{self.name}"
            )
            raise KeyError(
                f"Could not find dataset {self.__class__.__name__}.{self.name}"
            )
        # the dataset should have some strict subset of our fields
        for n in data:
            setattr(self, n, data[n])  # This will fail if the field is not in the class


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


EOMS = [
    Eom(
        name="repump_eom",
        frequency=3285.0 * MHz,
        attenuation=17.0 * dB,
        mirny_ch="mirny_eom_repump",
        almazny_ch="almazny_eom_repump",
    )
]
# Convert to dict for ease of use
EOMS = {eom.name: eom for eom in EOMS}
