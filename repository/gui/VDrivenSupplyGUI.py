"""Qt controls for configured VDrivenSupply objects."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator
from PyQt5.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from artiq.language import units as artiq_units

from managers.FastinoManager import VDrivenSupplyManager
from repository.models import VDrivenSupply


def unit_scale(unit: str) -> float:
    """Return the ARTIQ base-unit scale for a devices.py unit string."""
    try:
        return float(getattr(artiq_units, unit))
    except AttributeError as exc:
        raise ValueError(f"Unknown ARTIQ unit {unit!r}") from exc


def to_display_units(value: float, unit: str) -> float:
    return value / unit_scale(unit)


def from_display_units(value: float, unit: str) -> float:
    return value * unit_scale(unit)


def format_value(value: float) -> str:
    """Compact formatting suitable for both A-level and MHz-level values."""
    return f"{value:.9g}"


class SupplySwitch(QWidget):
    """Small ON/OFF button whose state changes only after its callback succeeds."""

    def __init__(self, enabled: bool, set_enabled):
        super().__init__()
        self.state = bool(enabled)
        self.set_enabled = set_enabled

        layout = QVBoxLayout()
        self.button = QPushButton()
        self.button.setCheckable(True)
        self.button.clicked.connect(self.toggle)
        layout.addWidget(self.button)
        self.setLayout(layout)
        self._refresh()

    def _refresh(self):
        self.button.setChecked(False)
        self.button.setText("ON" if self.state else "OFF")
        self.button.setStyleSheet(
            "background-color: #5db75d" if self.state else "background-color: #b75d5d"
        )

    def set_state(self, enabled: bool) -> None:
        self.state = bool(enabled)
        self._refresh()

    def toggle(self):
        self.state = bool(self.set_enabled(not self.state))
        self._refresh()


class SingleVDrivenSupply(QWidget):
    """Control one named VDrivenSupply in its configured physical units."""

    SLIDER_SCALE = 1000

    def __init__(
        self,
        manager: VDrivenSupplyManager,
        supply: VDrivenSupply,
        bridge,
    ):
        super().__init__()
        self.manager = manager
        self.supply = supply
        self.bridge = bridge
        self.scale = unit_scale(supply.unit)
        self._updating_controls = False

        minimum, maximum = manager.get_limits(supply.name)
        self.minimum = minimum / self.scale
        self.maximum = maximum / self.scale

        self.groupbox = QGroupBox()
        layout = QVBoxLayout()
        self.groupbox.setLayout(layout)

        top = QHBoxLayout()
        self.enable_switch = SupplySwitch(
            manager.get_enabled(supply.name),
            lambda enabled: bridge.change_control(
                f"supply.{supply.name}.enabled", enabled
            ),
        )
        top.addWidget(self.enable_switch)
        top.addStretch()

        title = QLabel(f"Ch {supply.ch} - {supply.name}")
        title.setStyleSheet("font: bold 12pt")
        top.addWidget(title)
        layout.addLayout(top)

        display_gain = supply.gain / self.scale
        self.metadata = QLabel(f"Gain: {format_value(display_gain)} {supply.unit}/V")
        layout.addWidget(self.metadata)

        self.text = QLineEdit()
        self.text.setValidator(
            QDoubleValidator(self.minimum, self.maximum, 9, self.text)
        )
        self.text.setAlignment(Qt.AlignCenter)
        self.text.editingFinished.connect(self._set_from_text)
        layout.addWidget(self.text)

        slider_line = QHBoxLayout()
        slider_line.addWidget(
            QLabel(f"{format_value(self.minimum)} <b>{supply.unit}</b>")
        )

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(
            round(self.minimum * self.SLIDER_SCALE),
            round(self.maximum * self.SLIDER_SCALE),
        )
        self.slider.setSingleStep(1)
        self.slider.valueChanged.connect(self._set_from_slider)
        slider_line.addWidget(self.slider)

        slider_line.addWidget(
            QLabel(f"{format_value(self.maximum)} <b>{supply.unit}</b>")
        )
        layout.addLayout(slider_line)

        self._set_controls(self.displayed_output())

        if supply.disabled:
            self.groupbox.setEnabled(False)
            self.groupbox.setToolTip("Disabled in devices.py")

    def displayed_output(self) -> float:
        return self.manager.get_output(self.supply.name) / self.scale

    def _set_controls(self, displayed_value: float) -> None:
        self._updating_controls = True
        try:
            self.text.setText(format_value(displayed_value))
            self.slider.blockSignals(True)
            self.slider.setValue(round(displayed_value * self.SLIDER_SCALE))
            self.slider.blockSignals(False)
        finally:
            self._updating_controls = False

    def _set_from_text(self) -> None:
        if self._updating_controls:
            return
        try:
            displayed_value = float(self.text.text())
        except ValueError:
            self._set_controls(self.displayed_output())
            return
        self.set_displayed_output(displayed_value)

    def _set_from_slider(self, slider_value: int) -> None:
        if self._updating_controls:
            return
        self.set_displayed_output(slider_value / self.SLIDER_SCALE)

    def set_displayed_output(self, displayed_value: float) -> float:
        displayed_value = min(max(float(displayed_value), self.minimum), self.maximum)
        output = from_display_units(displayed_value, self.supply.unit)
        output = self.bridge.change_control(f"supply.{self.supply.name}.value", output)
        displayed_output = to_display_units(output, self.supply.unit)
        self._set_controls(displayed_output)
        return displayed_output

    def refresh(self) -> None:
        self.enable_switch.set_state(self.manager.get_enabled(self.supply.name))
        self._set_controls(self.displayed_output())

    def get_widget(self):
        return self.groupbox


class VDrivenSuppliesGUI(QWidget):
    """Display every VDrivenSupply configured for the selected Fastino."""

    def __init__(
        self,
        manager: VDrivenSupplyManager,
        bridge,
        rows_per_column: int = 3,
    ):
        super().__init__()
        self.manager = manager
        self.bridge = bridge
        self.setWindowTitle("Voltage-driven supplies")

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.channels = [
            SingleVDrivenSupply(manager, supply, bridge) for supply in manager.supplies
        ]

        grid = QGridLayout()
        for index, channel in enumerate(self.channels):
            grid.addWidget(
                channel.get_widget(),
                index % rows_per_column,
                index // rows_per_column,
            )
        layout.addLayout(grid)
        self.bridge.state_changed.connect(self.refresh)

    def refresh(self, _state=None) -> None:
        for channel in self.channels:
            channel.refresh()
