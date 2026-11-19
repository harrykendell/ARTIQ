"""Timeout-bounded host-only access to the ARTIQ-managed TC-08 controller.

The controller (not this lightweight ARTIQ local device) owns the USB and
SQLite history. A fresh Sipyco RPC connection per request prevents a failed
logger from blocking a host-side absorption-image acquisition indefinitely.
"""
from __future__ import annotations

import math


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
        except Exception as error:
            return {"available": False, "connected": False,
                    "error": str(error)[:160]}

    def get_config(self):
        return self._request("get_config")

    def get_latest(self):
        return self._request("get_latest")

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
