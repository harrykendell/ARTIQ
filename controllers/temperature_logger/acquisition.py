"""Continuous, single-owner TC-08 acquisition and recorded-data RPC target.

The ARTIQ controller manager owns this process. The only task touching the
Pico SDK is _acquisition(); every RPC method serves memory or SQLite records.
"""
from __future__ import annotations

import asyncio
import logging
import time

from .pico import PicoTC08
from .store import TemperatureStore, validate_channel

log = logging.getLogger(__name__)
SAMPLE_INTERVAL_S = 5.0


class TemperatureController:
    def __init__(self, store: TemperatureStore, *, stop=None,
                 driver_factory=PicoTC08, interval=SAMPLE_INTERVAL_S):
        if interval <= 0:
            raise ValueError("TC-08 sampling interval must be positive")
        self.store = store
        self.stop = stop if stop is not None else asyncio.Event()
        self._driver_factory = driver_factory
        self.interval = float(interval)
        self.connected = False
        self.recording_ok = True
        self.cold_junction_c = None
        self.last_sample_at = None
        self.last_success_at = None
        self.last_error = None
        self._latest = {}
        self._reconfigure = asyncio.Event()
        self._configured_revision = None

    # Sipyco RPC interface: host-side cached/recorded data, never USB calls.
    def ping(self):
        # The controller is alive even while the USB logger is disconnected.
        return True

    def terminate(self):
        self.stop.set()
        self._reconfigure.set()

    def get_config(self):
        return self.store.config()

    def get_latest(self):
        config = self.store.config()
        now = time.time()
        readings = {}
        for entry in config["channels"]:
            if not entry["enabled"]:
                continue
            ch = entry["channel"]
            previous = self._latest.get(ch)
            if not previous or previous["revision"] != config["revision"]:
                readings[str(ch)] = {
                    "timestamp": None, "value_c": None, "valid": False,
                    "status": "awaiting_sample", "age_s": None,
                }
                continue
            age = max(0.0, now - previous["timestamp"])
            readings[str(ch)] = {
                "timestamp": previous["timestamp"],
                "value_c": previous["value_c"], "status": previous["status"],
                "age_s": age,
                "valid": (self.connected and self.recording_ok
                          and previous["status"] == "ok"
                          and age <= 3 * self.interval),
            }
        return {
            "available": True, "connected": self.connected,
            "recording_ok": self.recording_ok,
            "timestamp": self.last_sample_at,
            "last_success": self.last_success_at,
            "cold_junction_c": self.cold_junction_c if self.connected else None,
            "last_error": self.last_error, "revision": config["revision"],
            "channels": config["channels"], "readings": readings,
            "sample_interval_s": self.interval,
        }

    def get_channel(self, channel):
        ch = validate_channel(channel)
        return self.get_latest()["readings"].get(str(ch), {
            "timestamp": None, "value_c": None, "valid": False,
            "status": "disabled", "age_s": None,
        })

    def get_nearest(self, timestamp):
        enabled = [entry["channel"] for entry in self.store.config()["channels"]
                   if entry["enabled"]]
        return {
            "available": True,
            "connected": self.connected and self.recording_ok,
            "observation_timestamp": timestamp,
            "readings": self.store.nearest(timestamp, enabled),
        }

    async def get_history(self, start, end, channels, max_points=600):
        # A full seven-day history may inspect ~1 million rows; never hold
        # the controller's event loop (or delay its acquisition task).
        return await asyncio.to_thread(
            self.store.history, start, end, channels, max_points)

    def configure_channel(self, channel, expected_revision):
        updated = self.store.update_channel(channel, expected_revision)
        self._reconfigure.set()
        log.info("TC-08 configuration revision %d", updated["revision"])
        return updated

    def _record(self, config, readings, cjc):
        now = time.time()
        self.store.append(now, config, readings, cjc)
        self.last_sample_at = now
        for entry in config["channels"]:
            ch = entry["channel"]
            if not entry["enabled"]:
                self._latest.pop(ch, None)
                continue
            record = readings.get(ch, {"value_c": None, "status": "missing"})
            self._latest[ch] = {
                "timestamp": now, "revision": config["revision"],
                "value_c": record.get("value_c"),
                "status": record.get("status", "missing"),
            }

    async def _acquisition(self):
        """The sole Pico SDK owner; storage failures must not stop acquisition."""
        driver = None
        last_prune = 0.0
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                try:
                    # Keep SQLite timeouts out of the controller RPC event loop.
                    config = await asyncio.to_thread(self.store.config)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    log.exception("TC-08 configuration storage unavailable; retrying")
                    self.recording_ok = False
                    self.last_error = f"Configuration storage unavailable: {error}"[:160]
                    config = None

                if config is not None:
                    channels = [entry["channel"] for entry in config["channels"]
                                if entry["enabled"]]
                    read_succeeded = False
                    try:
                        if driver is None:
                            driver = self._driver_factory()
                            await asyncio.to_thread(driver.open)
                            self._configured_revision = None
                            log.info("Pico TC-08 connected")
                        if self._configured_revision != config["revision"]:
                            await asyncio.to_thread(driver.configure, config["channels"])
                            self._configured_revision = config["revision"]
                        readings, cjc = await asyncio.to_thread(driver.read, channels)
                        self.connected = True
                        self.cold_junction_c = cjc
                        read_succeeded = True
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        # Only USB/SDK faults should close and reopen the driver.
                        log.warning("Pico TC-08 unavailable: %s", error)
                        self.connected = False
                        self.cold_junction_c = None
                        self.last_error = str(error)[:160]
                        readings = {
                            ch: {"value_c": None, "status": "disconnected"}
                            for ch in channels
                        }
                        cjc = None
                        if driver is not None:
                            try:
                                await asyncio.to_thread(driver.close)
                            except Exception:
                                log.exception("Pico TC-08 close failed")
                        driver = None
                        self._configured_revision = None

                    try:
                        # Persist only once. Retrying a failed SQLite write
                        # from an exception handler would fail again (e.g. full
                        # disk) and terminate this acquisition task.
                        await asyncio.to_thread(self._record, config, readings, cjc)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        self.recording_ok = False
                        self.last_error = f"Temperature recording failed: {error}"[:160]
                        log.exception("Failed to persist TC-08 readings; will retry next sample")
                    else:
                        self.recording_ok = True
                        if read_succeeded:
                            self.last_error = None
                            self.last_success_at = self.last_sample_at

                if time.monotonic() - last_prune > 3600:
                    try:
                        removed = await asyncio.to_thread(self.store.prune)
                        if removed:
                            log.info("Pruned %d expired TC-08 readings", removed)
                    except Exception:
                        log.exception("TC-08 retention failed")
                    last_prune = time.monotonic()
                if self.stop.is_set():
                    break
                self._reconfigure.clear()
                remaining = max(0.1, self.interval - (time.monotonic() - started))
                try:
                    await asyncio.wait_for(self._reconfigure.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.connected = False
            if driver is not None:
                try:
                    await asyncio.to_thread(driver.close)
                except Exception:
                    log.exception("Pico TC-08 close failed on shutdown")
