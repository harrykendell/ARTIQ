import sys
import re
import logging
from pydantic.dataclasses import dataclass

from pint import UnitRegistry
from pint.util import infer_base_unit

sys.path.append(__file__.split("repository")[0] + "repository")

device_arrays = {}  # This will be filled with the devices from devices.py
# Create a unit registry for handling units
# - default format means we get MHz not megahertz
ureg = UnitRegistry(autoconvert_offset_to_baseunit=True)
ureg.default_format = "~"


@dataclass
class DEVICE:
    name: str

    @classmethod
    def __class_getitem__(cls, name: str | list[str]):
        """returns the initialized subclass(s)from devices.py"""
        if type(name) is not str:
            return [cls.__class_getitem__(n) for n in name]
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

    def to_file(self, filepath="repository/models/devices.py", light_touch=True):
        """Updates the device.py file with the current values of the device"""
        with open(
            filepath,
            "r",
        ) as file:
            text = file.read()
        dfn = self._get_def(text)
        new_dfn = self._new_def(dfn, light_touch=light_touch)
        text = text[: dfn["start"]] + new_dfn + text[dfn["end"] :]
        with open(filepath, "w") as file:
            file.write(text)

    def _get_def(self, text):
        """
        Finds the definition of this device in the devices.py file
        This is a helper function for to_file that handles the parsing of
        the devices.py file. It finds the start and end index of the
        definition of this device and returns it as a dict.

        :param text: The text of the devices.py file
        :return: A dict with the start and end index of the definition
        and the definition itself.
        """
        # Pair up parens
        op = []
        dc = {
            op.pop() if op else -1: i
            for i, c in enumerate(text)
            if (c == "(" and op.append(i) and False) or (c == ")" and op)
        }
        if dc.get(-1) or op:
            raise ValueError("Unmatched parentheses in devices.py")

        # narrow the search and verify we have the name
        for n in dc.keys():
            start = n - len(self.__class__.__name__)
            end = dc[n] + 1
            dfn = text[start:end]
            logging.debug(f"looking at string[{start}:{end}]: {dfn}")
            if dfn.startswith(self.__class__.__name__):
                if tocomma := dfn.find(","):
                    pattern = f"name\\s*=\\s*['\"]{self.name}['\"]"
                    if re.search(
                        pattern,
                        dfn[:tocomma],
                    ):
                        logging.info(f"Found {self.name} in devices.py:\n{dfn}")
                        return {
                            "start": n - len(self.__class__.__name__),
                            "end": dc[n] + 1,
                            "definition": dfn,
                        }
        raise ValueError(f"'{self.name}' not found in devices.py")

    def _new_def(self, definition, light_touch=True):
        """
        Creates the filled out constructor for this device
        This is a helper function for to_file that handles the creation of
        the new definition.

        :param definition: The original definition of this device
        :param light_touch: If True, only changed values are replaced in the definition.
        :return: The new definition as a string
        """
        try:
            changed = []
            new_def = definition["definition"]

            if light_touch:
                # we will only deal with values that have changed
                exec(
                    "from repository.models.devices import *;\
                        global duplicate_dev;duplicate_dev="
                    + definition["definition"],
                    globals(),
                    locals(),
                )
                for field in self.__dataclass_fields__:
                    if getattr(self, field) != getattr(
                        globals()["duplicate_dev"], field
                    ):
                        changed.append(field)
            else:
                # we will deal with all values
                changed = list(self.__dataclass_fields__.keys())

            # Process each field in the dataclass
            for field in changed:
                new_val = getattr(self, field)
                if new_val is None:
                    continue

                # Search for the parameter in the original definition
                match = re.search(
                    rf"(({field}\s*=\s*)([^,\n]+))", definition["definition"]
                )

                # If the field is not found, we need to add it at the end
                if not match:
                    lines = new_def.splitlines()
                    for i in reversed(range(len(lines))):
                        if lines[i].strip().endswith(","):
                            lines.insert(
                                i + 1,
                                re.match(r"\s*", lines[i]).group()
                                + f"{field}={new_val},",
                            )
                            break
                    new_def = "\n".join(lines)
                    continue

                old_val = match.group(3).strip()
                new_val = self._format_field(field, old_val, new_val)

                # Write our new value into the definition
                new_def = new_def.replace(
                    f"{match.group(0)}",
                    f"{match.group(2)}{new_val}",
                )

            return new_def

        except Exception as e:
            raise e
            logging.error(f"Could not save {getattr(self,'name')} back to file.\n{e}")

    def _format_field(self, field_name, old_value, new_value):
        """
        Format the field value for the new definition
        This is a helper function for _new_def that handles the formatting of
        different types of values. It ensures that the new value is formatted
        correctly for the devices.py file.

        :param field_name: The name of the field being formatted
        :param old_value: The original value of the field
        :param new_value: The new value of the field
        :return: The formatted value as a string
        """
        # Format the value
        # bools, or pure numbers don't need converting
        if isinstance(new_value, (bool, str)) or re.match(
            r"^[\d.,\s*+-/*]+$", old_value
        ):
            formatted_value = repr(new_value)
        # strings we preserve quote type
        elif isinstance(new_value, str):
            quote = old_value[0]
            formatted_value = f"{quote}{new_value}{quote}"
        elif isinstance(new_value, (int, float)):
            # Try to handle units
            try:
                res = ureg(old_value)
                new_quant = (
                    ureg.Quantity(new_value, infer_base_unit(res))
                    .to(res.units)
                    .round(10)
                )
                formatted_value = f"{new_quant.m} * {new_quant.u}"
            except Exception as e:
                formatted_value = repr(new_value)
                logging.warning(
                    f"Could not preserve units for\
                            {getattr(self,'name')}.{field_name}.\n{e}"
                )
        else:
            logging.warning(
                f"Defaulted to repr for {field_name}:\
                                {type(new_value)}"
            )
            formatted_value = repr(new_value)

        return formatted_value
