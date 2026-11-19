"""TC-08 acquisition, SDK, SQLite, IPC and persistence contract tests."""
from __future__ import annotations

import asyncio
import ctypes as ct
import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "controllers"))

from temperature_logger.pico import PicoError, PicoTC08
from temperature_logger.acquisition import TemperatureController
from temperature_logger.store import (
    RETENTION_SECONDS, TemperatureStore, validate_configuration,
)


def channel(ch=1, **changes):
    config = {
        "channel": ch, "name": f"Channel {ch}", "type": "K",
        "enabled": True, "record_with_experiments": True,
    }
    return {**config, **changes}


@pytest.fixture
def store(tmp_path):
    return TemperatureStore(tmp_path / "history.sqlite3")


def enable(store, ch=1, **changes):
    version = store.config()["revision"]
    return store.update_channel(channel(ch, **changes), version)


def test_configuration_defaults_disabled_persistent_and_revised(store):
    config = store.config()
    assert len(config["channels"]) == 8
    assert not any(item["enabled"] for item in config["channels"])
    with pytest.raises(ValueError):
        validate_configuration(channel(type=[]))
    with pytest.raises(ValueError):
        validate_configuration(channel(name="bad\nname"))
    with pytest.raises(ValueError):
        validate_configuration(channel(enabled=False, record_with_experiments=True))
    config = enable(store, 2, name="Optical table", type="J")
    assert config["revision"] == 1
    assert config["channels"][1]["name"] == "Optical table"
    with pytest.raises(ValueError, match="changed"):
        store.update_channel(channel(3), 0)
    reopened = TemperatureStore(store.path)
    assert reopened.config() == config
    assert reopened.config()["channels"][0]["enabled"] is False


def test_disabled_sensor_keeps_its_recorded_history_for_the_website(store):
    """Disabling acquisition must not make previous readings inaccessible."""
    enabled = enable(store, 1, name="Former chamber sensor", type="T")
    timestamp = time.time() - 10
    store.append(timestamp, enabled, {
        1: {"value_c": 19.75, "status": "ok"}
    }, 20.0)
    disabled = dict(enabled["channels"][0],
                    enabled=False, record_with_experiments=False)
    updated = store.update_channel(disabled, enabled["revision"])
    assert updated["channels"][0]["enabled"] is False
    rows = store.history(timestamp - 1, timestamp + 1, [1])["rows"]
    assert len(rows) == 1
    assert rows[0][2] == 19.75
    assert (rows[0][6], rows[0][7]) == ("Former chamber sensor", "T")
    assert store.nearest(timestamp, [1])["1"]["name"] == "Former chamber sensor"


def test_concurrent_config_updates_cannot_overwrite(store):
    barrier = threading.Barrier(3)
    results = []
    def attempt(ch):
        barrier.wait()
        try:
            store.update_channel(channel(ch), 0)
            results.append(True)
        except ValueError:
            results.append(False)
    first = threading.Thread(target=attempt, args=(1,))
    second = threading.Thread(target=attempt, args=(2,))
    first.start()
    second.start()
    barrier.wait()
    first.join()
    second.join()
    assert sorted(results) == [False, True]
    assert sum(item["enabled"] for item in store.config()["channels"]) == 1


def test_history_retains_extrema_invalids_gaps_and_metadata(store):
    config = enable(store, 1, name="MOT chamber", type="T")
    start = time.time() - 1000
    for i in range(101):
        status = "overflow" if i == 30 else "ok"
        val = 123.0 if i == 61 else (-19.0 if i == 65 else 20 + i / 100)
        store.append(start + 5 * i, config, {
            1: {"value_c": None if status != "ok" else val, "status": status}
        }, 24.3)
    store.append(start + 850, config, {1: {"value_c": 23.5, "status": "ok"}}, 24.4)
    assert store.nearest(start + 10.1)["1"]["value_c"] == 20.02
    result = store.history(start - 1, start + 860, [1], max_points=60)
    rows = result["rows"]
    assert len(rows) <= 60
    assert any(row[2] == -19 for row in rows)
    assert any(row[2] == 123 for row in rows)
    assert any(row[3] == "overflow" for row in rows)
    assert all(row[6] == "MOT chamber" and row[7] == "T" for row in rows)
    gap_start = next(row[8] for row in rows if row[0] == start + 500)
    gap_after = next(row[8] for row in rows if row[0] == start + 850)
    assert gap_start != gap_after
    changed = store.update_channel(channel(1, name="Renamed", type="J"), config["revision"])
    store.append(start + 860, changed, {1: {"status": "ok", "value_c": 24.0}}, 21.0)
    newer = store.nearest(start + 860)["1"]
    assert (newer["name"], newer["type"], newer["revision"]) == ("Renamed", "J", 2)
    assert store.nearest(start + 5)["1"]["name"] == "MOT chamber"


def test_retention_restart_and_bounds(store):
    config = enable(store)
    base = time.time()
    store.append(base - RETENTION_SECONDS - 20, config,
                 {1: {"status": "ok", "value_c": 20.0}}, 18)
    store.append(base - RETENTION_SECONDS + 20, config,
                 {1: {"status": "invalid", "value_c": float("nan")}}, float("nan"))
    assert store.prune(now=base) == 1
    assert len(TemperatureStore(store.path).history(
        base - RETENTION_SECONDS, base, [1])["rows"]) == 1
    assert TemperatureStore(store.path).history(
        base - RETENTION_SECONDS, base, [1])["rows"][0][2] is None
    for args in ((base - RETENTION_SECONDS - 10, base, [1]),
                 (base - 10, base, []), (base - 10, base, [9])):
        with pytest.raises(ValueError):
            store.history(*args)


def test_parallel_sqlite_reads_and_writes(store):
    config = enable(store)
    failures = []
    barrier = threading.Barrier(3)
    def writer():
        barrier.wait()
        try:
            for index in range(100):
                store.append(1000 + index, config,
                             {1: {"status": "ok", "value_c": float(index)}}, 21)
        except Exception as error:
            failures.append(error)
    def reader():
        barrier.wait()
        try:
            for _ in range(50):
                store.history(999, 1101, [1], max_points=50)
                store.nearest(1042)
        except Exception as error:
            failures.append(error)
    threads = [threading.Thread(target=func) for func in (writer, reader)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert not failures
    assert store.nearest(1099)["1"]["value_c"] == 99


class FakeFunction:
    def __init__(self, name, impl=None):
        self.name = name
        self.impl = impl or (lambda *args: 1)
        self.calls = []
        self.argtypes = []
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.impl(*args)


class FakeSDK:
    def __init__(self, fail_single=False):
        self.usb_tc08_open_unit = FakeFunction("open", lambda: 7)
        self.usb_tc08_close_unit = FakeFunction("close")
        self.usb_tc08_set_mains = FakeFunction("mains")
        self.usb_tc08_set_channel = FakeFunction("channel")
        def sample(handle, values, overflow, units):
            assert handle == 7 and units == 0
            if fail_single:
                return 0
            for index in range(9):
                values[index] = 20.0 + index
            overflow._obj.value = 1 << 3
            return 1
        self.usb_tc08_get_single = FakeFunction("single", sample)
        self.usb_tc08_get_last_error = FakeFunction("error", lambda *_: 42)


def test_sdk_configured_inputs_cjc_overflow_and_single_open():
    lib = FakeSDK()
    dev = PicoTC08(library=lib)
    dev.open()
    assert lib.usb_tc08_set_mains.calls == [(7, 0)]
    assert lib.usb_tc08_set_channel.calls[0] == (7, 0, ord("C"))
    dev.configure([channel(1, type="T"),
                   channel(2, enabled=False, record_with_experiments=False),
                   channel(3, type="J")])
    assert lib.usb_tc08_set_channel.calls[-3:] == [
        (7, 1, ord("T")), (7, 2, ord(" ")), (7, 3, ord("J"))
    ]
    readings, cjc = dev.read([1, 3])
    assert cjc == 20
    assert readings[1] == {"value_c": 21.0, "status": "ok"}
    assert readings[3] == {"value_c": None, "status": "overflow"}
    with pytest.raises(PicoError):
        dev.open()
    dev.close()
    assert lib.usb_tc08_close_unit.calls == [(7,)]
    with pytest.raises(PicoError):
        dev.read([1])


def test_sdk_failures_report_errors_and_close():
    lib = FakeSDK(fail_single=True)
    dev = PicoTC08(library=lib)
    dev.open()
    with pytest.raises(PicoError, match="SDK error 42"):
        dev.read([1])
    dev.close()


def test_acquisition_reconnects_without_consumer_usb_access(store):
    enable(store)
    instances = []
    class FakeDriver:
        def __init__(self):
            self.closed = False
            self.calls = 0
            instances.append(self)

        def open(self):
            pass

        def configure(self, entries):
            assert entries[0]["enabled"] is True
            assert entries[1]["enabled"] is False

        def read(self, enabled_channels):
            self.calls += 1
            if len(instances) == 1:
                raise OSError("USB disconnected")
            return {1: {"value_c": 22.5, "status": "ok"}}, 22.1

        def close(self):
            self.closed = True

    async def exercise():
        controller = TemperatureController(store, driver_factory=FakeDriver, interval=0.01)
        task = asyncio.create_task(controller._acquisition())
        await asyncio.sleep(0.13)
        controller.terminate()
        await asyncio.wait_for(task, timeout=1)
        return controller
    controller = asyncio.run(exercise())
    assert len(instances) >= 2
    assert all(instance.closed for instance in instances)
    assert store.nearest(time.time())["1"]["status"] == "ok"
    assert controller.last_success_at is not None
    assert controller.get_latest()["connected"] is False


def test_controller_rpc_contract_is_cached_and_reconfigurable(store):
    controller = TemperatureController(store)
    assert controller.ping() is True
    assert controller.get_latest()["readings"] == {}
    assert controller.get_channel(1)["status"] == "disabled"
    cfg = controller.configure_channel(channel(1, name="Cold atom chamber"), 0)
    assert cfg["revision"] == 1
    assert controller.get_config()["channels"][0]["record_with_experiments"]
    assert controller.get_latest()["readings"]["1"]["status"] == "awaiting_sample"
    assert asyncio.run(controller.get_history(1000, 1001, [1]))["rows"] == []
    with pytest.raises(ValueError, match="changed"):
        controller.configure_channel(channel(2), 0)
    with pytest.raises(ValueError):
        controller.get_channel(9)
    controller.connected = True
    controller._record(cfg, {1: {"value_c": 22.5, "status": "ok"}}, 21.0)
    snapshot = controller.get_latest()
    assert snapshot["readings"]["1"]["valid"] is True
    nearest = controller.get_nearest(snapshot["timestamp"])
    assert nearest["readings"]["1"]["value_c"] == 22.5
    controller.terminate()
    assert controller.stop.is_set()


def test_controller_exclusive_owner_and_loopback_rpc(store, monkeypatch, tmp_path):
    # No native Sipyco installation needed for an early owner-lock rejection.
    import sys
    import types
    import importlib.util
    entry = Path(__file__).parent.parent / "controllers/aqctl_temperature_logger.py"
    spec = importlib.util.spec_from_file_location("_tc08_controller_entry", entry)
    controller_entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller_entry)
    run_controller = controller_entry.run_controller

    rpc_module = types.ModuleType("sipyco.pc_rpc")
    rpc_module.Server = object
    monkeypatch.setitem(sys.modules, "sipyco", types.ModuleType("sipyco"))
    monkeypatch.setitem(sys.modules, "sipyco.pc_rpc", rpc_module)
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(run_controller(store.path, bind="0.0.0.0"))
    import fcntl
    owner_path = tmp_path / "owner.lock"
    fd = os.open(owner_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(BlockingIOError):
            asyncio.run(run_controller(store.path, port=3273))
    finally:
        os.close(fd)


def test_device_db_registers_locally_managed_native_controller():
    import runpy
    db = runpy.run_path(str(Path(__file__).parent.parent /
                            "repository/models/device_db.py"))["device_db"]
    entry = db["temperature_logger_controller"]
    assert entry["type"] == "controller"
    assert entry["host"] == "127.0.0.1"
    assert entry["port"] == 3273
    assert "launch_host" not in entry
    assert "controllers/aqctl_temperature_logger.py" in entry["command"]
    adapter = db["temperature_logger"]
    assert adapter["type"] == "local"
    assert adapter["module"] == "repository.utils.temperature_logger"
    assert adapter["arguments"]["timeout"] <= 0.5


def test_sqlite_write_failure_is_logged_without_restarting_usb_or_stopping_sampling(
        store, monkeypatch, caplog):
    """A full/busy SQLite database must never trigger a second failing write."""
    import logging

    enable(store)
    real_append = store.append
    attempts = []
    usb = {"open": 0, "read": 0, "close": 0}

    def flaky_append(*args):
        attempts.append(args)
        if len(attempts) <= 2:
            raise OSError("simulated disk full")
        return real_append(*args)

    monkeypatch.setattr(store, "append", flaky_append)

    class Driver:
        def open(self):
            usb["open"] += 1

        def configure(self, channels):
            pass

        def read(self, channels):
            usb["read"] += 1
            return {1: {"value_c": 21.5, "status": "ok"}}, 20.0

        def close(self):
            usb["close"] += 1

    async def exercise():
        controller = TemperatureController(
            store, driver_factory=Driver, interval=0.02
        )
        task = asyncio.create_task(controller._acquisition())
        try:
            await asyncio.sleep(0.06)
            assert not task.done()
            assert controller.connected
            assert not controller.recording_ok
            assert controller.get_latest()["recording_ok"] is False
            assert controller.get_nearest(time.time())["connected"] is False
            await asyncio.sleep(0.28)
            assert not task.done()
            assert controller.recording_ok
            assert controller.last_success_at is not None
            assert controller.get_latest()["readings"]["1"]["valid"] is True
        finally:
            controller.terminate()
            await asyncio.wait_for(task, timeout=2)

    with caplog.at_level(logging.ERROR):
        asyncio.run(exercise())

    assert usb["open"] == 1
    assert usb["close"] == 1  # Only the normal shutdown closes the SDK.
    assert usb["read"] == len(attempts) >= 3
    assert sum("Failed to persist TC-08 readings" in m for m in caplog.messages) == 2
    assert store.nearest(time.time())["1"]["value_c"] == 21.5


def test_configuration_database_failure_is_retried_without_crashing(
        store, monkeypatch, caplog):
    import logging

    enable(store)
    original_config = store.config
    calls = 0

    def flaky_config():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated SQLite read failure")
        return original_config()

    monkeypatch.setattr(store, "config", flaky_config)

    class Driver:
        def open(self):
            pass

        def configure(self, channels):
            pass

        def read(self, channels):
            return {1: {"value_c": 22.5, "status": "ok"}}, 20.0

        def close(self):
            pass

    async def exercise():
        controller = TemperatureController(store, driver_factory=Driver, interval=0.02)
        task = asyncio.create_task(controller._acquisition())
        try:
            await asyncio.sleep(0.24)
            assert not task.done()
            assert controller.recording_ok
            assert controller.last_success_at is not None
        finally:
            controller.terminate()
            await asyncio.wait_for(task, timeout=2)

    with caplog.at_level(logging.ERROR):
        asyncio.run(exercise())
    assert calls >= 2
    assert any("configuration storage unavailable" in m for m in caplog.messages)
