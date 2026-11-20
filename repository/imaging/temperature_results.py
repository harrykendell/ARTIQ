"""Auxiliary ndscan temperature results for absorption imaging.

The timestamp is observed at the beginning of the host-side image RPC,
AFTER the timed imaging kernel. It must not be described as a pulse timestamp.
Only a temperature value is pushed per selected channel for each analysed
absorption image; unavailable, stale and reconfigured probes produce NaN.
"""
from __future__ import annotations

import math

from ndscan.experiment import FloatChannel

MAX_SAMPLE_AGE_S = 15.0
LOW_PRIORITY = {"priority": -20}


def select_recorded_channels(configuration):
    """Freeze the physical channel/name/type mapping at fragment construction."""
    if not isinstance(configuration, dict) or configuration.get("available") is False:
        return []
    channels = configuration.get("channels", [])
    if not isinstance(channels, list):
        return []
    selected = []
    seen = set()
    for entry in channels:
        if not isinstance(entry, dict):
            continue
        ch = entry.get("channel")
        if (type(ch) is int and 1 <= ch <= 8 and ch not in seen
                and entry.get("enabled") is True and entry.get("record_with_experiments") is True):
            selected.append((ch, str(entry.get("name") or f"Channel {ch}"),
                             str(entry.get("type") or "K")))
            seen.add(ch)
    return sorted(selected)


def declare_temperature_results(fragment, configuration):
    """Freeze one temperature result per selected probe at fragment construction."""
    bindings = []
    for ch, name, tc_type in select_recorded_channels(configuration):
        label = f"{name} (TC-08 CH{ch}, type {tc_type})"
        result = fragment.setattr_result(
            f"lab_temp_ch{ch}", FloatChannel, description=label,
            unit="°C", scale=1.0, display_hints=dict(LOW_PRIORITY))
        bindings.append((ch, result, name, tc_type))
    return tuple(bindings)


def push_temperature_results(logger, bindings, observed_at):
    """Push one value or NaN per probe; never let logger faults abort imaging."""
    if not bindings:
        return
    try:
        snapshot = logger.get_nearest(observed_at) if logger is not None else {}
        readings = snapshot.get("readings") or {}
        connected = snapshot.get("connected") is True and snapshot.get("available") is not False
    except Exception:  # noqa: BLE001 - logger faults must never abort imaging
        readings = {}
        connected = False
    for ch, result, expected_name, expected_type in bindings:
        reading = readings.get(str(ch), {}) if isinstance(readings, dict) else {}
        reading = reading if isinstance(reading, dict) else {}
        try:
            age = abs(float(observed_at) - float(reading["timestamp"]))
        except (ValueError, TypeError, KeyError, OverflowError):
            age = math.inf
        value = reading.get("value_c")
        valid = (
            connected
            and reading.get("status") == "ok"
            and reading.get("valid") is True
            # Reject a probe reconfigured after this experiment was constructed.
            and reading.get("name") == expected_name
            and reading.get("type") == expected_type
            and math.isfinite(age)
            and age <= MAX_SAMPLE_AGE_S
            and type(value) in (float, int)
            and math.isfinite(value)
        )
        result.push(float(value) if valid else math.nan)
