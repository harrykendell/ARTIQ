from typing import List
from typing import Type

from artiq.experiment import HasEnvironment


def get_local_devices(hasEnv: HasEnvironment, classType: Type, module_name = None) -> List[str]:
    """Get all possible local devices of the passed type, including aliases

    Example usage::
        from artiq.coredevice.sampler import Sampler

        list_of_samplers = get_local_devices(self, Sampler)

    Args:
        hasEnv (HasEnvironment): An initiated HasEnvironment object
        classType (Type): The type of channel to be filtered for

    Returns:
        List[str]: List of names of all matching channels, prepended by aliases
    """

    class_name = classType.__name__
    if module_name == None:
        module_name = classType.__module__

    raw_channels = [
        k
        for k, v in hasEnv.get_device_db().items()
        if (
            isinstance(v, dict)
            and ("type" in v and v["type"] == "local")
            and ("module" in v and v["module"] == module_name)
            and ("class" in v and v["class"] == class_name)
        )
    ]

    alias_channels = [
        k
        for k, v in hasEnv.get_device_db().items()
        if (isinstance(k, str) and isinstance(v, str) and v in raw_channels)
    ]

    return alias_channels + raw_channels
