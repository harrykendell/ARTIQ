"""Real Sipyco RPC contract against a fake TC-08; no physical USB required."""
from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path

import pytest

sipyco = pytest.importorskip("sipyco")
from sipyco.pc_rpc import Client, Server

sys.path.insert(0, str(Path(__file__).parent.parent / "controllers"))
from temperature_logger.acquisition import TemperatureController
from temperature_logger.store import TemperatureStore


def test_controller_sipyco_round_trip_without_usb(tmp_path):
    class FakeTC08:
        def open(self):
            pass
        def configure(self, channels):
            assert channels[0]["enabled"]
        def read(self, channels):
            return {1: {"value_c": 24.125, "status": "ok"}}, 23.0
        def close(self):
            pass

    store = TemperatureStore(tmp_path / "history.sqlite3")
    initial = store.config()["channels"][0].copy()
    initial.update(enabled=True, record_with_experiments=True, name="MOT chamber")
    store.update_channel(initial, 0)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    async def run():
        controller = TemperatureController(store, driver_factory=FakeTC08, interval=0.05)
        server = Server({"temperature_logger": controller}, allow_parallel=True)
        await server.start("127.0.0.1", port)
        task = asyncio.create_task(controller._acquisition())
        try:
            await asyncio.sleep(0.15)

            def inspect_rpc():
                client = Client("127.0.0.1", port, "temperature_logger", timeout=1)
                try:
                    # Sipyco exports every public callable on the target. Do
                    # not accidentally expose the acquisition loop or SDK.
                    methods = set(client.get_rpc_method_list()["methods"])
                    assert methods == {
                        "ping", "terminate", "get_config", "get_latest",
                        "get_channel", "get_nearest", "get_history",
                        "configure_channel",
                    }
                    assert client.ping() is True
                    config = client.get_config()
                    latest = client.get_latest()
                    assert config["revision"] == 1
                    assert latest["connected"] is True
                    assert latest["readings"]["1"]["value_c"] == pytest.approx(24.125)
                    assert client.get_channel(1)["valid"] is True
                    when = latest["timestamp"]
                    assert client.get_nearest(when)["readings"]["1"]["status"] == "ok"
                    rows = client.get_history(time.time() - 60, time.time() + 1,
                                              [1], 100)["rows"]
                    assert rows and rows[-1][2] == pytest.approx(24.125)
                    changed = dict(config["channels"][0], name="Renamed probe")
                    assert client.configure_channel(changed, 1)["revision"] == 2
                    client.terminate()
                finally:
                    client.close_rpc()
            await asyncio.to_thread(inspect_rpc)
            assert controller.stop.is_set()
        finally:
            controller.terminate()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await server.stop()

    asyncio.run(run())

def test_custom_controller_manager_starts_loopback_service_on_lab_host():
    import importlib.util
    import runpy
    root = Path(__file__).parent.parent
    db = runpy.run_path(str(root / "repository/models/device_db.py"))["device_db"]
    entry = db["temperature_logger_controller"].copy()
    spec = importlib.util.spec_from_file_location(
        "_temperature_test_ctlmgr", root / "controllers/artiq_ctlmgr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manager = module.Controllers.__new__(module.Controllers)
    manager.host_filter = db["topticaDLC"]["host"]
    manager.active_or_queued = set()
    manager.queue = asyncio.Queue()
    manager["temperature_logger_controller"] = entry
    action, (name, planned) = manager.queue.get_nowait()
    assert action == "set" and name == "temperature_logger_controller"
    assert planned["command"].endswith("-p 3273 --bind 127.0.0.1")
    assert name in manager.active_or_queued
    # The existing externally addressed controllers still launch normally.
    manager["existing_controller"] = {
        "type": "controller", "host": manager.host_filter,
        "port": 12345, "command": "controller -p {port} --bind {bind}",
    }
    action, (name, planned) = manager.queue.get_nowait()
    assert action == "set" and name == "existing_controller"
    assert planned["command"].endswith("--bind " + manager.host_filter)
    # Unrelated remote hosts must not be launched by this manager.
    manager["remote_controller"] = {
        "type": "controller", "host": "192.0.2.55", "port": 12346,
        "command": "controller -p {port} --bind {bind}",
    }
    assert manager.queue.empty()
