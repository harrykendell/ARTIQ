"""Explicit, loopback-only control bridge for :mod:`artiq_gui`.

The device managers remain authoritative.  Every local and remote setter below
calls one of their existing concrete methods, then reads and publishes a fresh
canonical snapshot.  The IPC adapter accepts only ``get_state`` and
``set_control`` and marshals both onto the Qt/experiment thread.
"""

import json
import math
import socketserver
import threading
from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Callable

from artiq.language import units as artiq_units
from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal

MAX_IPC_BYTES = 256_000


@dataclass(frozen=True)
class _Control:
    id: str
    label: str
    type: str
    read: Callable[[], Any]
    write: Callable[[Any], None]
    scale: float = 1.0
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    disabled: bool = False
    advanced: bool = False

    def descriptor(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "value": self.read(),
        }
        if self.scale != 1.0:
            result["scale"] = self.scale
        if self.unit:
            result["unit"] = self.unit
        for key in ("minimum", "maximum", "step"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.disabled:
            result["disabled"] = True
        if self.advanced:
            result["advanced"] = True
        return result


class GuiControlBridge(QObject):
    """Small, auditable mapping from typed control names to manager setters."""

    state_changed = pyqtSignal(object)
    _request = pyqtSignal(object)

    def __init__(self, suservo, mirny, supplies):
        super().__init__()
        self.suservo = suservo
        self.mirny = mirny
        self.supplies = supplies
        self.controls: dict[str, _Control] = {}
        self._groups: list[dict[str, Any]] = []
        self._beam_channels = {
            beam.name: index for index, beam in enumerate(self.suservo.beams)
        }
        self._build_registry()
        self._request.connect(self._execute_request, Qt.QueuedConnection)

    def get_state(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "groups": [self._render_group(group) for group in self._groups],
        }

    def set_control(self, name: str, value: Any) -> dict[str, Any]:
        self.change_control(name, value)
        return self.get_state()

    def change_control(self, name: str, value: Any) -> Any:
        try:
            control = self.controls[name]
        except KeyError as error:
            raise ValueError("Unknown GUI control name") from error
        return self._change(lambda: control.write(value), control.read)

    def set_beam_iir(
        self, beam_name: str, p: Any, i: Any, gl: Any
    ) -> tuple[float, float, float]:
        try:
            channel = self._beam_channels[beam_name]
        except KeyError as error:
            raise ValueError("Unknown SUServo beam") from error
        p, i, gl = _finite(p), _finite(i), _finite(gl)
        return self._change(
            lambda: self.suservo.set_iir(channel, channel, p, i, gl),
            lambda: (
                _finite(self.suservo.Ps[channel]),
                _finite(self.suservo.Is[channel]),
                _finite(self.suservo.Gls[channel]),
            ),
        )

    def _build_registry(self) -> None:
        def add(control: _Control) -> str:
            if control.id in self.controls:
                raise ValueError(f"Duplicate GUI control id {control.id!r}")
            self.controls[control.id] = control
            return control.id

        def boolean_control(control_id, label, read, write, *, disabled=False):
            return add(
                _Control(
                    control_id,
                    label,
                    "boolean",
                    lambda: bool(read()),
                    lambda value: write(_boolean(value)),
                    disabled=disabled,
                )
            )

        def number_control(
            control_id,
            label,
            read,
            write,
            *,
            scale=1.0,
            unit="",
            minimum=None,
            maximum=None,
            step=None,
            integer=False,
            disabled=False,
            advanced=False,
        ):
            if integer:

                def validate(value):
                    return _integer(value, int(minimum), int(maximum))

            elif minimum is not None and maximum is not None:

                def validate(value):
                    return _bounded(value, minimum, maximum)

            else:
                validate = _finite
            return add(
                _Control(
                    control_id,
                    label,
                    "number",
                    lambda: _finite(read()),
                    lambda value: write(validate(value)),
                    scale=scale,
                    unit=unit,
                    minimum=minimum,
                    maximum=maximum,
                    step=step,
                    disabled=disabled,
                    advanced=advanced,
                )
            )

        suservo_enabled = boolean_control(
            "suservo.enabled",
            "Servo enabled",
            lambda: self.suservo.enabled,
            lambda enabled: (
                self.suservo.enable_servo() if enabled else self.suservo.disable_servo()
            ),
        )
        beam_devices = []
        for channel, beam in enumerate(self.suservo.beams):
            prefix = f"beam.{beam.name}"

            def set_iir_component(value, component, ch=channel):
                values = [
                    self.suservo.Ps[ch],
                    self.suservo.Is[ch],
                    self.suservo.Gls[ch],
                ]
                values[component] = value
                self.suservo.set_iir(ch, ch, *values)

            controls = [
                boolean_control(
                    f"{prefix}.output_enabled",
                    "Output",
                    lambda ch=channel: self.suservo.en_outs[ch],
                    lambda enabled, ch=channel: (
                        self.suservo.enable(ch) if enabled else self.suservo.disable(ch)
                    ),
                ),
                boolean_control(
                    f"{prefix}.iir_enabled",
                    "IIR",
                    lambda ch=channel: self.suservo.en_iirs[ch],
                    lambda enabled, ch=channel: (
                        self.suservo.enable_iir(ch)
                        if enabled
                        else self.suservo.disable_iir(ch)
                    ),
                ),
                number_control(
                    f"{prefix}.frequency",
                    "Frequency",
                    lambda ch=channel: self.suservo.freqs[ch] * 1e6,
                    lambda value, ch=channel: self.suservo.set_freq(ch, value / 1e6),
                    scale=1e6,
                    unit="MHz",
                    minimum=0.0,
                    maximum=400e6,
                ),
                number_control(
                    f"{prefix}.attenuation",
                    "Attenuation",
                    lambda ch=channel: self.suservo.atts[ch],
                    lambda value, ch=channel: self.suservo.set_att(ch, value),
                    unit="dB",
                    minimum=0.0,
                    maximum=31.5,
                ),
                number_control(
                    f"{prefix}.gain",
                    "Gain",
                    lambda ch=channel: self.suservo.gains[ch],
                    lambda value, ch=channel: self.suservo.set_gain(ch, value),
                    minimum=0,
                    maximum=3,
                    step=1,
                    integer=True,
                    advanced=True,
                ),
                number_control(
                    f"{prefix}.y",
                    "Y",
                    lambda ch=channel: self.suservo.ys[ch],
                    lambda value, ch=channel: self.suservo.set_y(ch, value),
                    minimum=0.0,
                    maximum=1.0,
                    advanced=True,
                ),
                number_control(
                    f"{prefix}.offset",
                    "Offset",
                    lambda ch=channel: self.suservo.offsets[ch],
                    lambda value, ch=channel: self.suservo.set_offset(ch, value),
                    unit="V",
                    minimum=-10.0,
                    maximum=10.0,
                    advanced=True,
                ),
                number_control(
                    f"{prefix}.p",
                    "P",
                    lambda ch=channel: self.suservo.Ps[ch],
                    lambda value, fn=set_iir_component: fn(value, 0),
                    advanced=True,
                ),
                number_control(
                    f"{prefix}.i",
                    "I",
                    lambda ch=channel: self.suservo.Is[ch],
                    lambda value, fn=set_iir_component: fn(value, 1),
                    advanced=True,
                ),
                number_control(
                    f"{prefix}.gl",
                    "gL",
                    lambda ch=channel: self.suservo.Gls[ch],
                    lambda value, fn=set_iir_component: fn(value, 2),
                    advanced=True,
                ),
            ]
            beam_devices.append({
                "id": prefix,
                "label": beam.name,
                "controls": controls,
            })

        shutter_devices = []
        for channel, shutter in enumerate(self.suservo.shutter_infos):
            prefix = f"shutter.{shutter.name}"
            control = boolean_control(
                f"{prefix}.open",
                "Open",
                lambda ch=channel: self.suservo.en_shutters[ch],
                lambda opened, ch=channel: (
                    self.suservo.open_shutter(ch)
                    if opened
                    else self.suservo.close_shutter(ch)
                ),
            )
            shutter_devices.append({
                "id": prefix,
                "label": shutter.name,
                "controls": [control],
            })

        eom_devices = []
        for eom, channel in zip(self.mirny.eoms, self.mirny.eom_channels):
            prefix = f"eom.{eom.name}"
            controls = [
                boolean_control(
                    f"{prefix}.almazny_enabled",
                    "Almazny",
                    lambda ch=channel: self.mirny.en_almazny[ch],
                    lambda enabled, ch=channel: (
                        self.mirny.enable_almazny(ch)
                        if enabled
                        else self.mirny.disable_almazny(ch)
                    ),
                ),
                boolean_control(
                    f"{prefix}.output_enabled",
                    "Output",
                    lambda ch=channel: self.mirny.en_outs[ch],
                    lambda enabled, ch=channel: (
                        self.mirny.enable(ch) if enabled else self.mirny.disable(ch)
                    ),
                ),
                number_control(
                    f"{prefix}.frequency",
                    "Frequency",
                    lambda ch=channel: self.mirny.freqs[ch] * 1e6,
                    lambda value, ch=channel: self.mirny.set_freq(ch, value / 1e6),
                    scale=1e6,
                    unit="MHz",
                    minimum=53.125e6,
                    maximum=6800e6,
                ),
                number_control(
                    f"{prefix}.attenuation",
                    "Attenuation",
                    lambda ch=channel: self.mirny.atts[ch],
                    lambda value, ch=channel: self.mirny.set_att(ch, value),
                    unit="dB",
                    minimum=0.0,
                    maximum=31.5,
                ),
            ]
            eom_devices.append({"id": prefix, "label": eom.name, "controls": controls})

        supply_devices = []
        for supply in self.supplies.supplies:
            prefix = f"supply.{supply.name}"
            minimum, maximum = self.supplies.get_limits(supply.name)
            disabled = bool(supply.disabled)
            controls = [
                boolean_control(
                    f"{prefix}.enabled",
                    "Enabled",
                    lambda name=supply.name: self.supplies.get_enabled(name),
                    lambda enabled, name=supply.name: self.supplies.set_enabled(
                        name, enabled
                    ),
                    disabled=disabled,
                ),
                number_control(
                    f"{prefix}.value",
                    "Output",
                    lambda name=supply.name: self.supplies.get_output(name),
                    lambda value, name=supply.name: self.supplies.set_output(
                        name, value
                    ),
                    scale=_unit_scale(supply.unit),
                    unit=str(supply.unit),
                    minimum=_finite(minimum),
                    maximum=_finite(maximum),
                    disabled=disabled,
                ),
            ]
            supply_devices.append({
                "id": prefix,
                "label": supply.name,
                "controls": controls,
            })

        self._groups = [
            {
                "id": "suservo",
                "label": "SUServo",
                "controls": [suservo_enabled],
                "devices": beam_devices,
            },
            {"id": "shutters", "label": "Shutters", "devices": shutter_devices},
            {"id": "mirny", "label": "Mirny", "devices": eom_devices},
            {"id": "supplies", "label": "Supplies", "devices": supply_devices},
        ]

    def _render_group(self, group: dict[str, Any]) -> dict[str, Any]:
        result = {"id": group["id"], "label": group["label"]}
        if group.get("controls"):
            result["controls"] = [
                self.controls[control_id].descriptor()
                for control_id in group["controls"]
            ]
        result["devices"] = [
            {
                "id": device["id"],
                "label": device["label"],
                "controls": [
                    self.controls[control_id].descriptor()
                    for control_id in device["controls"]
                ],
            }
            for device in group["devices"]
        ]
        return result

    def invoke(self, method: str, **arguments: Any) -> dict[str, Any]:
        if QThread.currentThread() == self.thread():
            return self._invoke(method, arguments)
        request = _PendingRequest(method=method, arguments=arguments)
        self._request.emit(request)
        if not request.done.wait(15.0):
            raise TimeoutError("GUI thread did not answer the control request")
        if request.error is not None:
            raise request.error
        return request.result

    def _execute_request(self, request: "_PendingRequest") -> None:
        try:
            request.result = self._invoke(request.method, request.arguments)
        except Exception as error:
            request.error = error
        finally:
            request.done.set()

    def _invoke(self, method: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if method == "get_state" and not arguments:
            return self.get_state()
        if method == "set_control" and set(arguments) == {"name", "value"}:
            name = arguments["name"]
            if not isinstance(name, str) or not name or len(name) > 240:
                raise ValueError("GUI control name is invalid")
            return self.set_control(name, arguments["value"])
        raise ValueError("Unknown GUI IPC operation")

    def _change(self, action: Callable[[], Any], read: Callable[[], Any]) -> Any:
        action()
        value = read()
        self.state_changed.emit(self.get_state())
        return value


@dataclass
class _PendingRequest:
    method: str
    arguments: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: Exception | None = None


class GuiControlAdapter:
    """One-request-per-connection JSON-line adapter bound to loopback only."""

    def __init__(
        self, bridge: GuiControlBridge, host: str = "127.0.0.1", port: int = 3259
    ):
        if host not in {"127.0.0.1", "::1"}:
            raise ValueError("GUI control adapter requires a literal loopback address")
        if not 1 <= int(port) <= 65535:
            raise ValueError("GUI control adapter port is invalid")
        self.bridge = bridge
        self.host = host
        self.port = int(port)
        self._server = None
        self._thread = None

    def start(self) -> None:
        if self._server is not None:
            return
        server = _LoopbackServer((self.host, self.port), _GuiRequestHandler)
        server.bridge = self.bridge
        thread = threading.Thread(
            target=server.serve_forever,
            name="artiq-gui-control-ipc",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)


class _LoopbackServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    bridge: GuiControlBridge


class _GuiRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            self.connection.settimeout(5.0)
            raw = self.rfile.readline(MAX_IPC_BYTES + 1)
            if not raw or len(raw) > MAX_IPC_BYTES or not raw.endswith(b"\n"):
                raise ValueError("GUI IPC request is invalid")
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("GUI IPC request must be an object")
            method = request.get("method")
            if method == "get_state" and set(request) == {"method"}:
                state = self.server.bridge.invoke("get_state")
            elif method == "set_control" and set(request) == {
                "method",
                "name",
                "value",
            }:
                state = self.server.bridge.invoke(
                    "set_control", name=request["name"], value=request["value"]
                )
            else:
                raise ValueError("Unknown GUI IPC operation")
            response = {"ok": True, "state": state}
        except Exception as error:
            response = {"ok": False, "error": str(error)[:500]}
        encoded = (
            json.dumps(
                response, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
            + b"\n"
        )
        if len(encoded) <= MAX_IPC_BYTES:
            self.wfile.write(encoded)


def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Expected a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Expected a finite number")
    return number


def _unit_scale(unit: Any) -> float:
    try:
        scale = float(getattr(artiq_units, str(unit)))
    except AttributeError as error:
        raise ValueError(f"Unknown ARTIQ unit {unit!r}") from error
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError(f"Invalid ARTIQ unit scale for {unit!r}")
    return scale


def _bounded(value: Any, minimum: float, maximum: float) -> float:
    number = _finite(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"Value must be between {minimum} and {maximum}")
    return number


def _integer(value: Any, minimum: int, maximum: int) -> int:
    number = _finite(value)
    if not number.is_integer() or not minimum <= number <= maximum:
        raise ValueError(f"Value must be an integer from {minimum} to {maximum}")
    return int(number)


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError("Expected a boolean")
    return value
