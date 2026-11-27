"""Hardware-independent tests of the qualified firmware workflow."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location(
    "lab_firmware", Path(__file__).resolve().parents[1] / "scripts/firmware.py"
)
firmware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firmware)


def test_real_pin():
    pin, board = firmware.load_pin()
    assert board["variant"] == "BU2402001"
    assert pin["source_repo"].endswith("/artiq-firmware")
    assert pin["build_flags"] == ["--analyzer-telemetry"]
    assert pin["config"]["rtio_analyzer_snapshot"] == "2"
    assert pin["snapshot"]["capacity"] == 2 * 1024 * 1024


def test_cached_image_mismatch_is_rejected(tmp_path):
    path = tmp_path / "top.bit"
    path.write_bytes(b"bad image")
    expected = hashlib.sha256(b"qualified image").hexdigest()
    with pytest.raises(RuntimeError, match="checksum-mismatched"):
        firmware.fetch_file("https://unused.invalid/top.bit", path, expected)
    assert path.read_bytes() == b"bad image"


def test_fetch_verified_and_atomic(tmp_path, monkeypatch):
    import io

    content = b"qualified image"
    monkeypatch.setattr(firmware, "urlopen", lambda *a, **kw: io.BytesIO(content))
    path = tmp_path / "top.bit"
    expected = hashlib.sha256(content).hexdigest()
    firmware.fetch_file("https://unused.invalid/top.bit", path, expected)
    assert path.read_bytes() == content
    wrong = tmp_path / "runtime.fbi"
    with pytest.raises(RuntimeError, match="checksum-mismatched"):
        firmware.fetch_file("https://unused.invalid/runtime.fbi", wrong, "0" * 64)
    assert not wrong.exists()
    assert list(tmp_path.iterdir()) == [path]


def test_dry_run_does_not_flash(tmp_path, monkeypatch):
    monkeypatch.setattr(firmware, "prepare", lambda _: tmp_path)
    command = Mock()
    monkeypatch.setattr(firmware.subprocess, "run", command)
    monkeypatch.setattr(
        firmware,
        "require_idle_host",
        Mock(side_effect=AssertionError("unexpected hardware check")),
    )
    firmware.main(["dry-run"])
    args = command.call_args.args[0]
    assert "-n" in args
    assert args[-3:] == ["gateware", "firmware", "start"]
    assert "bootloader" not in args and "storage" not in args


def test_flash_requires_confirmation(monkeypatch):
    monkeypatch.setattr(
        firmware, "prepare", Mock(side_effect=AssertionError("unexpected prepare"))
    )
    with pytest.raises(SystemExit) as exc:
        firmware.main(["flash"])
    assert exc.value.code == 2


def test_flash_requires_stopped_publisher(monkeypatch):
    run = Mock(return_value=Mock(stdout="active\n"))
    monkeypatch.setattr(firmware.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Stop artiq-viewer"):
        firmware.require_idle_host("192.168.0.2")
    run.assert_called_once()


def test_build_never_flashes(tmp_path, monkeypatch):
    pin, board = firmware.load_pin()
    monkeypatch.setattr(firmware, "load_pin", lambda: (pin, board))
    monkeypatch.setattr(firmware, "CONFIG", tmp_path)
    run = Mock()
    monkeypatch.setattr(firmware.subprocess, "run", run)
    firmware.main(["build"])
    args = run.call_args.args[0]
    assert any(pin["source_revision"] in a for a in args)
    assert "--analyzer-telemetry" in args
    assert "artiq_flash" not in args


def test_wrong_board_configuration_fails(tmp_path, monkeypatch):
    pin, _ = firmware.load_pin()
    (tmp_path / "firmware.json").write_text(json.dumps(pin))
    (tmp_path / pin["board"]).write_text("{}")
    monkeypatch.setattr(firmware, "CONFIG", tmp_path)
    monkeypatch.setattr(firmware, "PIN", tmp_path / "firmware.json")
    with pytest.raises(RuntimeError, match="checksum-mismatched"):
        firmware.load_pin()


def test_protocol_probe_uses_empty_tail_and_validates_capability(monkeypatch):
    pin, _ = firmware.load_pin()
    token = b"a" * 16
    monkeypatch.setattr(firmware.uuid, "uuid4", lambda: Mock(bytes=token))
    tail = 2**64 - 1
    reply = struct.pack(
        "<4sIQQQQII", b"RTS1", 0, tail, 64, 64, 64, 2097152, 49
    ) + struct.pack(
        "<4s11Q16s8Q",
        b"RTP4",
        *([0] * 11),
        token,
        pin["snapshot"]["features"],
        *([0] * 7),
    )
    mock = Mock()
    # Return short pieces to exercise the exact framing loop.
    chunks = bytearray(reply)

    def receive(n):
        result = bytes(chunks[: min(n, 7)])
        del chunks[: len(result)]
        return result

    mock.recv.side_effect = receive
    mock.__enter__ = Mock(return_value=mock)
    mock.__exit__ = Mock(return_value=False)
    connect = Mock(
        side_effect=[mock, ConnectionRefusedError(), ConnectionRefusedError()]
    )
    monkeypatch.setattr(firmware.socket, "create_connection", connect)
    firmware.verify_snapshot(pin, "192.168.0.2")
    mock.sendall.assert_called_once_with(struct.pack("<4sQ16s", b"RTQ9", tail, token))
