"""Timeout-bounded host-only access to the ARTIQ-managed TC-08 controller.

The controller (not this lightweight ARTIQ local device) owns the USB and
SQLite history. A fresh Sipyco RPC connection per request prevents a failed
logger from blocking a host-side absorption-image acquisition indefinitely.
"""
from __future__ import annotations

import math
import time


class TemperatureLogger:
    def __init__(self, dmgr=None, *, host="127.0.0.1", port=3273,
                 timeout=0.35, rpc_factory=None):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._rpc_factory = rpc_factory
        if not 0 < self.timeout <= 10:
            raise ValueError("TC-08 RPC timeout must be positive and bounded")

    def _request(self, method, *arguments):
        try:
            factory = self._rpc_factory
            if factory is None:
                from sipyco.pc_rpc import Client
                factory = Client
            client = factory(self.host, self.port, "temperature_logger",
                             timeout=self.timeout)
            try:
                return getattr(client, method)(*arguments)
            finally:
                client.close_rpc()
        except Exception as error:  # noqa: BLE001 - return unavailable on RPC faults
            return {"available": False, "connected": False,
                    "error": str(error)[:160]}

    def get_config(self):
        return self._request("get_config")

    def get_latest(self):
        return self._request("get_latest")

    def read(self):
        """Read cached temperatures without triggering a TC-08 acquisition.

        Returns temperatures in °C (NaN for invalid/stale measurements),
        with per-probe timestamps and validity. Physical channels are keyed
        by their numeric IDs; the internal cold junction is separate.
        """
        snapshot = self.get_latest()
        if not isinstance(snapshot, dict):
            snapshot = {}
        connected = (
            snapshot.get("available") is True
            and snapshot.get("connected") is True
            and snapshot.get("recording_ok") is not False
        )
        latest_time = snapshot.get("timestamp")
        interval = snapshot.get("sample_interval_s", 5.0)
        cjc = snapshot.get("cold_junction_c")
        cjc_valid = (
            connected and type(cjc) in (int, float) and math.isfinite(cjc)
            and type(latest_time) in (int, float) and math.isfinite(latest_time)
            and 0 <= time.time() - latest_time <= 3 * interval
        )
        readings = snapshot.get("readings") or {}
        if not isinstance(readings, dict):
            readings = {}
        channels = {}
        for entry in snapshot.get("channels") or []:
            if not isinstance(entry, dict) or entry.get("enabled") is not True:
                continue
            channel = entry.get("channel")
            if type(channel) is not int or not 1 <= channel <= 8:
                continue
            sample = readings.get(str(channel), {})
            value = sample.get("value_c") if isinstance(sample, dict) else None
            valid = (
                connected and isinstance(sample, dict)
                and sample.get("valid") is True and sample.get("status") == "ok"
                and type(value) in (int, float) and math.isfinite(value)
            )
            channels[channel] = {
                "temperature_c": float(value) if valid else math.nan,
                "timestamp": sample.get("timestamp") if isinstance(sample, dict) else None,
                "valid": valid,
            }
        return {
            "available": snapshot.get("available") is True,
            "connected": connected,
            "timestamp": latest_time,
            "cold_junction_c": float(cjc) if cjc_valid else math.nan,
            "channels": channels,
        }

    def get_channel(self, channel):
        if type(channel) is not int or not 1 <= channel <= 8:
            raise ValueError("Thermocouple channel must be 1..8")
        return self._request("get_channel", channel)

    def get_nearest(self, timestamp):
        try:
            observation = float(timestamp)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Invalid observation timestamp") from None
        if not math.isfinite(observation) or observation < 0:
            raise ValueError("Invalid observation timestamp")
        return self._request("get_nearest", observation)
