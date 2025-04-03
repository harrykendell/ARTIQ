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

import sys
import logging
from pydantic.dataclasses import dataclass

device_arrays = {}  # This will be filled with the devices from devices.py


@dataclass
class DEVICE:
    name: str

    @classmethod
    def __class_getitem__(cls, name: str | list[str]):
        """returns the initialized subclass(s) with the data from its dataset or defaults to devices.py"""
        if type(name) is not str:
            return [cls.__class_getitem__(n) for n in name]
        try:
            # implicitly capture what we hope is the owning Experiment
            hasEnv = sys._getframe(1).f_locals["self"]
            ret = cls(name=name)
            ret.update_from_dataset(hasEnv)
            return ret
        except Exception as e:
            logging.debug(
                f"Could not load from dataset {cls.__name__}.{name}, defaulting to devices.py\n {e}"
            )
            # try to get it from devices.py instead
            return device_arrays[cls][name]

    @classmethod
    def keys(cls):
        """All device names of the associated type"""
        return list(device_arrays[cls].keys())

    @classmethod
    def values(cls):
        """All device of the associated type"""
        return list(device_arrays[cls].values())

    @classmethod
    def all(cls):
        """All key:devices of the associated type"""
        return device_arrays[cls]

    def to_file(self):
        """Updates the device.py file with the current values of the device"""
        with open(
            sys.path.append(
                __file__.split("repository")[0] + "repository/models/devices.py"
            ),
            "r",
        ) as file:
            text = file.read()
            start, end = get_definition(text, self)
            text = text[:start] + to_string(self) + text[end:]
            file.write(text)


def get_definition(string, dev):
    # Pair up parens
    op = []
    dc = {
        op.pop() if op else -1: i
        for i, c in enumerate(string)
        if (c == "(" and op.append(i) and False) or (c == ")" and op)
    }
    if dc.get(-1) or op:
        raise ValueError("Unmatched parentheses in string")
    # narrow the search and verify we have the name
    for n in dc.keys():
        dfn = string[n - len(dev.__class__.__name__) : dc[n] + 1]
        if string[n - len(dev.__class__.__name__) : n] == dev.__class__.__name__:
            if tocomma := dfn[n:].find(","):
                print(f"looking at string[{n}:{tocomma}]")
                if (
                    f"'{dev.name}'" in string[n:tocomma]
                    or f'"{dev.name}"' in string[n:tocomma]
                ):
                    print(f"found {dev.name} in {dfn}")
                    return n - len(dev.__class__.__name__), dc[n] + 1
    raise ValueError(f"'{dev.name}' not found in string")


def to_string(device):
    """Renders the filled constructor to a string."""
    return (
        f"{device.__class__.__name__}(\n"
        + "".join(
            [
                f"\t{k} = {repr(getattr(device,k))},\n"
                for k in device.__dataclass_fields__
                if getattr(device, k) is not None
            ]
        )
        + "    )"
    )
