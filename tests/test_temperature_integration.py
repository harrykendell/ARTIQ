"""TC-08 ndscan result-channel integration without ARTIQ hardware.

An ARTIQ host-only adapter makes bounded Sipyco RPC requests to the native
controller. The controller's acquisition and RPC contracts have their own
tests in test_temperature_controller.py.
"""
from __future__ import annotations

import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest

from repository.utils.temperature_logger import TemperatureLogger


def test_artiq_adapter_uses_bounded_sipyco_rpc_and_closes_every_client():
    calls = []
    class FakeClient:
        def __init__(self, host, port, target, timeout=None):
            calls.append(("connect", host, port, target, timeout))
        def get_config(self):
            return {"available": True, "channels": []}
        def get_latest(self):
            return {"available": True, "connected": True}
        def get_channel(self, ch):
            return {"channel": ch, "status": "ok"}
        def get_nearest(self, timestamp):
            return {"available": True, "connected": True,
                    "observation_timestamp": timestamp, "readings": {}}
        def close_rpc(self):
            calls.append(("close",))
    logger = TemperatureLogger(rpc_factory=FakeClient, timeout=0.3)
    assert logger.get_config()["available"] is True
    assert logger.get_latest()["connected"] is True
    assert logger.get_channel(2)["channel"] == 2
    assert logger.get_nearest(1000)["observation_timestamp"] == 1000
    assert len([c for c in calls if c[0] == "connect"]) == 4
    assert len([c for c in calls if c[0] == "close"]) == 4
    assert all(c == ("connect", "127.0.0.1", 3273, "temperature_logger", 0.3)
               for c in calls if c[0] == "connect")


def test_artiq_adapter_is_best_effort_and_never_reads_usb():
    def timeout(*args, **kwargs):
        raise TimeoutError("Controller request stalled")
    logger = TemperatureLogger(rpc_factory=timeout)
    assert logger.get_config()["available"] is False
    assert logger.get_nearest(1000)["available"] is False
    assert logger.get_latest()["connected"] is False
    with pytest.raises(ValueError):
        logger.get_channel(9)
    with pytest.raises(ValueError):
        logger.get_nearest(float("nan"))


@pytest.fixture
def results_module(monkeypatch):
    ndscan = types.ModuleType("ndscan")
    experiment = types.ModuleType("ndscan.experiment")
    class FloatChannel:
        pass
    experiment.FloatChannel = FloatChannel
    monkeypatch.setitem(sys.modules, "ndscan", ndscan)
    monkeypatch.setitem(sys.modules, "ndscan.experiment", experiment)
    module_path = Path(__file__).parent.parent / "repository/imaging/temperature_results.py"
    spec = importlib.util.spec_from_file_location("_temperature_results_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Sink:
    def __init__(self, name, cls, props):
        self.name = name
        self.cls = cls
        self.props = props
        self.values = []

    def push(self, value):
        self.values.append(value)


class Fragment:
    def __init__(self):
        self.outputs = {}

    def setattr_result(self, name, channel_type, **props):
        assert name not in self.outputs
        self.outputs[name] = Sink(name, channel_type, props)
        return self.outputs[name]


def config():
    return {"available": True, "revision": 5, "channels": [
        {"channel": 2, "name": "Optical table", "type": "T",
         "enabled": True, "record_with_experiments": True},
        {"channel": 1, "name": "MOT chamber", "type": "K",
         "enabled": True, "record_with_experiments": True},
        {"channel": 3, "name": "Open circuit", "type": "K",
         "enabled": False, "record_with_experiments": False},
        {"channel": 4, "name": "Unrecorded", "type": "J",
         "enabled": True, "record_with_experiments": False}
    ]}


def test_dynamic_channel_names_types_and_low_priority(results_module):
    fragment = Fragment()
    bindings = results_module.declare_temperature_results(fragment, config())
    assert [item[0] for item in bindings] == [1, 2]
    assert sorted(fragment.outputs) == sorted([
        "lab_temp_ch1", "lab_temp_ch1_age_s", "lab_temp_ch1_valid",
        "lab_temp_ch2", "lab_temp_ch2_age_s", "lab_temp_ch2_valid",
    ])
    value = fragment.outputs["lab_temp_ch1"]
    assert value.props["description"].startswith("MOT chamber (TC-08 CH1, type K)")
    assert value.props["unit"] == "°C" and value.props["scale"] == 1.0
    assert value.props["display_hints"]["priority"] < 0
    assert fragment.outputs["lab_temp_ch1_age_s"].props["unit"] == "s"
    assert fragment.outputs["lab_temp_ch1_valid"].props["display_hints"]["priority"] < 0


def test_one_value_per_declared_channel_per_acquisition(results_module):
    fragment = Fragment()
    bindings = results_module.declare_temperature_results(fragment, config())
    class Logger:
        calls = 0
        def get_nearest(self, timestamp):
            self.calls += 1
            assert timestamp == 1000
            return {
                "available": True, "connected": True, "readings": {
                    "1": {"value_c": 21.5, "valid": True, "status": "ok",
                          "timestamp": 999.0},
                    "2": {"value_c": 22.0, "valid": True, "status": "ok",
                          "timestamp": 800.0}
                }
            }
    logger = Logger()
    results_module.push_temperature_results(logger, bindings, 1000)
    assert logger.calls == 1
    assert fragment.outputs["lab_temp_ch1"].values == [21.5]
    assert fragment.outputs["lab_temp_ch1_age_s"].values == [1.0]
    assert fragment.outputs["lab_temp_ch1_valid"].values == [1.0]
    assert math.isnan(fragment.outputs["lab_temp_ch2"].values[0])
    assert fragment.outputs["lab_temp_ch2_age_s"].values == [200.0]
    assert fragment.outputs["lab_temp_ch2_valid"].values == [0.0]
    # A second shot advances EVERY existing numeric channel by one value,
    # even though the logger could not be reached.
    results_module.push_temperature_results(None, bindings, 1005)
    for result in fragment.outputs.values():
        assert len(result.values) == 2
    assert math.isnan(fragment.outputs["lab_temp_ch1"].values[-1])
    assert math.isnan(fragment.outputs["lab_temp_ch1_age_s"].values[-1])


def test_snapshot_schema_stays_fixed_and_rejects_invalid_samples(results_module):
    fragment = Fragment()
    configuration = config()
    bindings = results_module.declare_temperature_results(fragment, configuration)
    configuration["channels"].clear()
    assert len(fragment.outputs) == 6
    results_module.push_temperature_results(
        types.SimpleNamespace(get_nearest=lambda timestamp: {
            "available": True, "connected": False,
            "readings": {
                "1": {"value_c": 30, "status": "ok", "valid": True,
                      "timestamp": timestamp}
            }
        }), bindings, 1000)
    assert math.isnan(fragment.outputs["lab_temp_ch1"].values[0])
    assert fragment.outputs["lab_temp_ch1_valid"].values[0] == 0.0
    assert fragment.outputs["lab_temp_ch2_valid"].values[0] == 0.0


def test_failed_nearest_query_never_interrupts_result_pushing(results_module):
    fragment = Fragment()
    bindings = results_module.declare_temperature_results(fragment, config())
    class Logger:
        def get_nearest(self, timestamp):
            raise ConnectionError("socket gone")
    results_module.push_temperature_results(Logger(), bindings, 1000)
    assert all(len(item.values) == 1 for item in fragment.outputs.values())
    assert all(math.isnan(fragment.outputs[f"lab_temp_ch{ch}"].values[0])
               for ch in (1, 2))


def test_existing_imaging_and_rtio_kernel_remain_untouched():
    source = (Path(__file__).parent.parent /
              "repository/imaging/absorption_image.py").read_text()
    assert 'self.image_timestamp.push(frame_timestamp)' in source
    assert 'temperature_observed_at = time()' in source
    assert 'self.set_dataset(\n            "Images.absorption.timestamp"' in source
    assert "push_temperature_results(" in source
    assert "self.custom_objective.push(" in source
    assert "self.atom_number.push(" in source
