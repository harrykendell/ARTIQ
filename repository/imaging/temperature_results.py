"""Auxiliary ndscan temperature results for absorption imaging.

The timestamp is observed at the beginning of the host-side image RPC,
AFTER the timed imaging kernel. It must not be described as a pulse timestamp.
One value, one sample-age and one validity flag are pushed per configured
channel for every successfully analysed absorption-image acquisition.
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
    """Return immutable channel bindings (index, temperature, age, validity, TC type)."""
    bindings = []
    for ch, name, tc_type in select_recorded_channels(configuration):
        label = f"{name} (TC-08 CH{ch}, type {tc_type})"
        value = fragment.setattr_result(
            f"lab_temp_ch{ch}", FloatChannel, description=label,
            unit="°C", scale=1.0, display_hints=dict(LOW_PRIORITY))
        age = fragment.setattr_result(
            f"lab_temp_ch{ch}_age_s", FloatChannel,
            description=f"{label} sample age relative to host observation",
            unit="s", scale=1.0, display_hints=dict(LOW_PRIORITY))
        valid = fragment.setattr_result(
            f"lab_temp_ch{ch}_valid", FloatChannel,
            description=f"{label} freshness/validity (1=valid, 0=invalid)",
            display_hints=dict(LOW_PRIORITY))
        bindings.append((ch, value, age, valid, tc_type))
    return tuple(bindings)


def push_temperature_results(logger, bindings, observed_at):
    """Query recorded samples only; logger faults must not affect image results."""
    if not bindings:
        return
    try:
        snapshot = logger.get_nearest(observed_at) if logger is not None else {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        readings = snapshot.get("readings") or {}
        connected = snapshot.get("connected") is True and snapshot.get("available") is not False
    except Exception:  # noqa: BLE001 - logger faults must never abort imaging
        readings = {}
        connected = False
    for ch, value_channel, age_channel, valid_channel, expected_type in bindings:
        reading = readings.get(str(ch), {}) if isinstance(readings, dict) else {}
        reading = reading if isinstance(reading, dict) else {}
        try:
            timestamp = float(reading["timestamp"])
            age = abs(float(observed_at) - timestamp)
            if not math.isfinite(age):
                raise ValueError("Invalid sample timestamp")
        except (ValueError, TypeError, KeyError, OverflowError):
            age = math.nan
        sample = reading.get("value_c")
        valid = (connected and reading.get("status") == "ok"
                 and reading.get("type", expected_type) == expected_type
                 and reading.get("valid") is True and math.isfinite(age)
                 and age <= MAX_SAMPLE_AGE_S
                 and type(sample) in (float, int) and math.isfinite(sample))
        value_channel.push(float(sample) if valid else math.nan)
        age_channel.push(age)
        valid_channel.push(1.0 if valid else 0.0)
