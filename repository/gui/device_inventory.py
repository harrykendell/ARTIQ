"""Resolve semantic device definitions onto logical GUI manager channels."""

import re
from collections.abc import Iterable
from typing import Any

from repository.models.device_db import device_db


def logical_channel(device_alias: str, prefix: str) -> int:
    """Resolve an ARTIQ alias such as ``suservo_aom_MOT`` to its channel."""

    target = device_alias
    visited = set()
    while target in device_db and isinstance(device_db[target], str):
        if target in visited:
            raise ValueError(f"Cyclic device alias at {device_alias!r}")
        visited.add(target)
        target = device_db[target]

    match = re.fullmatch(rf"{re.escape(prefix)}([0-9]+)", target)
    if match is None:
        raise ValueError(
            f"Device alias {device_alias!r} does not resolve to {prefix}<index>"
        )
    return int(match.group(1))


def configured_in_channel_order(
    devices: Iterable[Any], alias_attribute: str, prefix: str
) -> list[Any]:
    """Return semantic devices sorted by their physical logical channel."""

    configured = list(devices)
    channels = [
        logical_channel(getattr(device, alias_attribute), prefix)
        for device in configured
    ]
    if len(channels) != len(set(channels)):
        raise ValueError(
            f"Multiple configured devices resolve to the same {prefix} channel"
        )
    return [
        device
        for _, device in sorted(
            zip(channels, configured), key=lambda item: (item[0], item[1].name)
        )
    ]


def physical_channel_aliases(prefix: str) -> list[str]:
    """Return physical ``device_db`` channel names in logical index order."""

    channels = []
    for name, definition in device_db.items():
        match = re.fullmatch(rf"{re.escape(prefix)}([0-9]+)", name)
        if match is not None and not isinstance(definition, str):
            channels.append((int(match.group(1)), name))
    if not channels:
        raise ValueError(f"No physical {prefix} channels are defined")
    channels.sort()
    indices = [index for index, _ in channels]
    if indices != list(range(max(indices) + 1)):
        raise ValueError(f"Physical {prefix} channels must be contiguous from zero")
    return [name for _, name in channels]
