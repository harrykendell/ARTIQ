import json
import logging
import os
import sys

# Avoid loading unnecessary GTK integration in this Qt-only GUI.
os.environ.pop("XDG_CURRENT_DESKTOP", None)

# Suppress Qt's harmless GLX framebuffer warnings.
os.environ["QT_LOGGING_RULES"] = "qt.glx.warning=false"

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from managers.boosterTelemetry import BoosterTelemetry
from managers.FastinoManager import VDrivenSupplyManager
from managers.MirnyManager import MirnyManager
from VDrivenSupplyGUI import VDrivenSuppliesGUI
from control_bridge import GuiControlAdapter, GuiControlBridge
from device_inventory import (
    configured_in_channel_order,
    logical_channel,
    physical_channel_aliases,
)

# disable formatting
# flake8: noqa
from managers.SUServoManager import SUServoManager

from artiq.coredevice.core import Core
from artiq.experiment import EnvExperiment, kernel, rpc
from artiq.language import StringValue, BooleanValue, MHz, ms
from repository.models.devices import (
    EOMS,
    SHUTTERS,
    SUSERVOED_BEAMS,
    VDRIVEN_SUPPLIES,
)


class Switch(QWidget):
    def __init__(
        self,
        default: bool,
        turn_on,
        turn_off,
        on_text="ON",
        off_text="OFF",
        colors=None,
    ):
        super().__init__()
        self.turn = [turn_on, turn_off]
        self.state = default
        self.text = [off_text, on_text]
        self.color = colors or [
            "background-color: #b75d5d",
            "background-color: #5db75d",
        ]
        # Main layout for this widget
        layout = QVBoxLayout()

        self.button = QPushButton()
        self.button.setText(self.text[default])
        self.button.setCheckable(True)
        self.button.setStyleSheet(self.color[default])
        self.button.setFixedWidth(
            max(
                self.button.fontMetrics().boundingRect(i).width() + 20
                for i in self.text
            )
        )
        self.button.clicked.connect(self.switch_state)

        layout.addWidget(self.button)

        self.setLayout(layout)

    def switch_state(self):
        """Toggles the state of this button"""
        self.button.setChecked(False)  # we dont want the button to stay held down
        previous = self.state
        canonical = self.turn[previous]()
        # Bridge callbacks return the manager state after reading it back.  Keep
        # supporting older callbacks which only performed the action.
        self.set_state(not previous if canonical is None else canonical)

    def set_state(self, state):
        self.state = bool(state)
        self.button.setChecked(False)
        self.button.setText(self.text[self.state])
        self.button.setStyleSheet(self.color[self.state])


class SignalDoubleSpinBox(QDoubleSpinBox):
    stepChanged = pyqtSignal()

    def stepBy(self, step):
        value = self.value()
        super(QDoubleSpinBox, self).stepBy(step)
        if self.value() != value:
            self.stepChanged.emit()


class DDSControl(QWidget):
    def __init__(
        self,
        manager,
        set_frequency,
        set_attenuation,
        ch=0,
        minimum=0.0,
        maximum=400.0,
    ):
        super().__init__()
        self.min = minimum
        self.max = maximum
        self.manager = manager
        self.ch = ch
        self.set_frequency = set_frequency
        self.set_attenuation = set_attenuation

        # Main layout for this widget
        layout = QVBoxLayout()

        # labels
        freq_label = QLabel("Frequency (MHz)")
        att_label = QLabel("Attenuation (dB)")

        labelline = QHBoxLayout()
        labelline.addWidget(freq_label)
        labelline.addStretch()
        labelline.addWidget(att_label)
        layout.addLayout(labelline)

        # text inputs
        self.text = QLineEdit()
        self.text.setText(str(round(self.manager.freqs[ch], 3)))
        self.text.setValidator(QDoubleValidator())
        self.text.setAlignment(Qt.AlignCenter)
        self.text.editingFinished.connect(lambda: self.setfreq(self.text.text()))

        self.att_input = SignalDoubleSpinBox()
        self.att_input.setRange(0.0, 31.5)
        self.att_input.setSingleStep(0.5)
        self.att_input.setDecimals(1)
        self.att_input.setValue(self.manager.atts[ch])
        self.att_input.setSuffix(" dB")
        self.att_input.editingFinished.connect(
            lambda: self.set_attenuation(self.att_input.value())
        )
        self.att_input.stepChanged.connect(
            lambda: self.set_attenuation(self.att_input.value())
        )

        inputline = QHBoxLayout()
        inputline.addWidget(self.text)
        inputline.addStretch()
        inputline.addWidget(self.att_input)
        layout.addLayout(inputline)

        # Slider and min/max labels
        min_label = QLabel(f"{self.min} <b>MHz</b>")
        max_label = QLabel(f"{self.max} <b>MHz</b>")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setSingleStep(1)
        self.slider.setRange(int(self.min), int(self.max))
        self.slider.setValue(int(self.manager.freqs[ch]))
        self.slider.valueChanged.connect(lambda x: self.setfreq(x))

        sliderline = QHBoxLayout()
        sliderline.addWidget(min_label)
        sliderline.addWidget(self.slider)
        sliderline.addWidget(max_label)
        layout.addLayout(sliderline)
        self.setLayout(layout)

    def setfreq(self, val):
        # check its a valid number - if not the text edit went wrong
        try:
            val = float(val)
        except ValueError:
            self.text.setText(str(self.slider.value()))
            return

        # guard against recursion already at the correct frequency
        if val == self.manager.freqs[self.ch]:
            return

        val = min(max(val, self.min), self.max)
        self.text.setText(str(val))
        self.slider.blockSignals(True)
        self.slider.setValue(int(val))
        self.slider.blockSignals(False)

        self.set_frequency(val)

    def refresh(self):
        frequency = float(self.manager.freqs[self.ch])
        attenuation = float(self.manager.atts[self.ch])
        self.text.setText(str(round(frequency, 3)))
        self.slider.blockSignals(True)
        self.slider.setValue(int(frequency))
        self.slider.blockSignals(False)
        self.att_input.blockSignals(True)
        self.att_input.setValue(attenuation)
        self.att_input.blockSignals(False)


class BoosterControl(QWidget):
    def __init__(self, manager, set_tab, ch=0):
        super().__init__()
        self.manager = manager
        self.set_tab = set_tab
        self.tripped = "unknown"
        layout = QVBoxLayout()

        # labels
        state = QHBoxLayout()
        state.setAlignment(Qt.AlignCenter)
        self.status = QLabel("-")
        state.addWidget(self.status)
        layout.addLayout(state)
        layout.addStretch()

        pows = QHBoxLayout()
        pows.setAlignment(Qt.AlignCenter)
        self.in_power = QLabel("0 <b>dBm</b>")
        pows.addWidget(self.in_power)
        rarrow = QLabel("<b>→</b>")
        rarrow.setStyleSheet("font-size: 20px")
        pows.addWidget(rarrow)
        self.out_power = QLabel("0 <b>dBm</b>")
        pows.addWidget(self.out_power)
        layout.addLayout(pows)

        ref = QHBoxLayout()
        carrow = QLabel("<b>↻</b>")
        carrow.setStyleSheet("font-size: 20px")
        ref.addWidget(carrow)
        ref.setAlignment(Qt.AlignCenter)
        self.ref_power = QLabel("0 <b>dBm</b>")
        ref.addWidget(self.ref_power)
        layout.addLayout(ref)

        layout.addStretch()
        self.setLayout(layout)

    def update(self, data):
        self.in_power.setText(f"{data['input_power']:.1f}<b> dBm</b>")
        self.out_power.setText(f"{data['output_power']:.1f}<b> dBm</b>")
        self.ref_power.setText(f"{data['reflected_power']:.1f}<b> dBm</b>")

        tripped = data["state"] != "Enabled"
        if tripped != self.tripped:
            if tripped:
                self.status.setText(f"<b><font color='red'>{data['state']}</font></b>")
                self.set_tab(2)
            else:
                self.status.setText(f"{data['state']}")
                self.set_tab(0)

        self.tripped = tripped


class PIDControl(QWidget):
    def __init__(self, manager, set_offset, set_y, set_iir, ch=0):
        super().__init__()
        self.manager: SUServoManager = manager
        self.en_out = self.manager.en_outs[ch]
        self.ch = ch
        self.set_offset = set_offset
        self.set_y = set_y
        self.set_iir = set_iir

        layout = QVBoxLayout()

        top = QHBoxLayout()
        top.addWidget(QLabel("Target (V)"))
        self.setpoint = QLineEdit()
        self.setpoint.setText(str(self.manager.offsets[ch]))
        self.setpoint.setValidator(QDoubleValidator(-10.00, 10.00, 10))
        self.setpoint.editingFinished.connect(
            lambda: self.set_offset(float(self.setpoint.text()))
        )
        top.addWidget(self.setpoint)

        # if we are visible we want to update the ADC value
        def update_adc():
            if self.isVisible():
                volt = self.manager.get_adc(ch)
                pow = "?? <b>mW</b>"
                g = self.manager.calib_gains[ch]
                o = self.manager.calib_offsets[ch]
                if g != 1.0 or o != 0.0:
                    power = g * volt + o
                    pow = f"{power / 1e3 if power > 500 else power if power >= 0.1 else power * 1e3:.1f} \
                        <b>{'W' if power > 500 else 'mW' if power >= 0.1 else 'uW'}</b>"
                self.adc_val.setText(
                    f"{pow} | {volt:.4f} <b>V</b> | \
                        {self.manager.get_y(ch) * 100:.0f}%"
                )

        self.adc_val = QLabel("?? <b>mW</b> | ?? <b>V</b> | ??%")
        top.addStretch()
        top.addWidget(self.adc_val)

        self.timer = QTimer()
        self.timer.timeout.connect(lambda: update_adc())
        self.timer.start(500)

        layout.addLayout(top)
        bottom = QHBoxLayout()

        # P I Gl linedits
        P_label = QLabel("P")
        bottom.addWidget(P_label)
        self.P = QLineEdit()
        self.P.setText(str(self.manager.Ps[ch]))
        self.P.setValidator(QDoubleValidator())
        self.P.editingFinished.connect(lambda: self.set())
        bottom.addWidget(self.P)
        I_label = QLabel("I")
        bottom.addWidget(I_label)
        self.I = QLineEdit()  # noqa: using 'I' makes sense in the context
        self.I.setText(str(self.manager.Is[ch]))
        self.I.setValidator(QDoubleValidator())
        self.I.editingFinished.connect(lambda: self.set())
        bottom.addWidget(self.I)
        Gl_label = QLabel("Gl")
        bottom.addWidget(Gl_label)
        self.Gl = QLineEdit()
        self.Gl.setText(str(self.manager.Gls[ch]))
        self.Gl.setValidator(QDoubleValidator())
        self.Gl.editingFinished.connect(lambda: self.set())
        bottom.addWidget(self.Gl)

        # Amplitude input
        amp_vbox = QVBoxLayout()
        amp_vbox.setAlignment(Qt.AlignBottom)
        amp_label = QLabel("Amplitude")

        amp_vbox.addWidget(amp_label)
        amp_vbox.addStretch()
        self.amp_input = SignalDoubleSpinBox()
        self.amp_input.setRange(0.0, 1.0)
        self.amp_input.setSingleStep(0.1)
        self.amp_input.setDecimals(1)
        self.amp_input.setValue(self.manager.ys[ch])
        self.amp_input.editingFinished.connect(
            lambda: self.set_y(self.amp_input.value())
        )
        self.amp_input.stepChanged.connect(lambda: self.set_y(self.amp_input.value()))
        amp_vbox.addWidget(self.amp_input)
        bottom.addLayout(amp_vbox)

        layout.addLayout(bottom)
        self.setLayout(layout)

    def set(self):
        self.set_iir(
            float(self.P.text()),
            float(self.I.text()),
            float(self.Gl.text()),
        )

    def refresh(self):
        self.setpoint.setText(str(self.manager.offsets[self.ch]))
        self.P.setText(str(self.manager.Ps[self.ch]))
        self.I.setText(str(self.manager.Is[self.ch]))
        self.Gl.setText(str(self.manager.Gls[self.ch]))
        self.amp_input.blockSignals(True)
        self.amp_input.setValue(float(self.manager.ys[self.ch]))
        self.amp_input.blockSignals(False)


class SamplerControl(QWidget):
    def __init__(self, manager, ch=0):
        super().__init__()
        self.manager = manager
        self.ch = ch

        layout = QVBoxLayout()

        self.setLayout(layout)

    @kernel
    def sample(self, gap=1 * ms, num=100):
        raise NotImplementedError


class SingleChannelSUServo(QWidget):
    """Class to control a single given SUServo channel"""

    def __init__(self, manager, bridge, boostermanager, beam, channel=0):
        # manager : SUServoManager
        QWidget.__init__(self)
        self.manager = manager
        self.channel = channel
        self.beam = beam
        self.bridge = bridge

        self.groupbox = QGroupBox()

        # Stack all other widgets vertically
        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # Top row: ON/OFF switch, PID switch, channel name
        # ON/OFF switch {{{
        top = QHBoxLayout()
        self.dds_button = Switch(
            default=self.manager.en_outs[channel],
            turn_on=lambda: self.bridge.change_control(
                f"beam.{beam.name}.output_enabled", True
            ),
            turn_off=lambda: self.bridge.change_control(
                f"beam.{beam.name}.output_enabled", False
            ),
        )
        top.addWidget(self.dds_button)
        if beam.name in {"CDT1", "CDT2"}:
            self.pulse = QWidget()
            pulse_layout = QHBoxLayout(self.pulse)
            pulse_layout.setContentsMargins(8, 8, 8, 8)
            pulse_layout.setSpacing(12)

            timing_layout = QVBoxLayout()
            timing_layout.setSpacing(4)
            timing_layout.addWidget(QLabel("On time (ms)"))
            self.pulse_on_time = QDoubleSpinBox()
            self.pulse_on_time.setRange(0.001, 10000.0)
            self.pulse_on_time.setDecimals(3)
            self.pulse_on_time.setSingleStep(1.0)
            self.pulse_on_time.setValue(100.0)
            self.pulse_on_time.setMaximumWidth(120)
            timing_layout.addWidget(self.pulse_on_time)
            timing_layout.addWidget(QLabel("Off time (ms)"))
            self.pulse_off_time = QDoubleSpinBox()
            self.pulse_off_time.setRange(0.0, 10000.0)
            self.pulse_off_time.setDecimals(3)
            self.pulse_off_time.setSingleStep(1.0)
            self.pulse_off_time.setValue(100.0)
            self.pulse_off_time.setMaximumWidth(120)
            timing_layout.addWidget(self.pulse_off_time)
            pulse_layout.addLayout(timing_layout)

            action_layout = QVBoxLayout()
            action_layout.setSpacing(4)
            self.pulse_button = QPushButton("Start pulsing")
            self.pulse_button.setMaximumWidth(120)
            self.pulse_button.setToolTip(
                "Start accurately timed AOM pulses; click again to stop after the current batch"
            )
            self.pulse_button.clicked.connect(self.start_pulsing)
            action_layout.addWidget(self.pulse_button)
            action_layout.addStretch(1)
            pulse_layout.addLayout(action_layout)
            pulse_layout.addStretch(1)
            self._pulse_running = False
            self._pulse_on_time = 0.0
            self._pulse_off_time = 0.0
            self._pulse_batch_count = 1
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setSingleShot(True)
            self._pulse_timer.timeout.connect(self._emit_next_pulse)
        self.pid_button = Switch(
            default=self.manager.en_iirs[channel],
            turn_on=lambda: self.bridge.change_control(
                f"beam.{beam.name}.iir_enabled", True
            ),
            turn_off=lambda: self.bridge.change_control(
                f"beam.{beam.name}.iir_enabled", False
            ),
            on_text="PID",
            off_text="PID",
        )
        top.addWidget(self.pid_button)
        # }}}

        top.addStretch()

        # Channel name
        name = QLabel(beam.name)
        name.setStyleSheet("font: bold 12pt")
        top.addWidget(name)

        vbox.addLayout(top)

        # Initialize tab screen
        self.tabs = QTabWidget()

        # DDS
        self.dds = DDSControl(
            self.manager,
            lambda value: (
                self.bridge.change_control(f"beam.{beam.name}.frequency", value * MHz)
                / MHz
            ),
            lambda value: self.bridge.change_control(
                f"beam.{beam.name}.attenuation", value
            ),
            ch=channel,
            minimum=0.0,
            maximum=400.0,
        )
        self.tabs.addTab(self.dds, "DDS")

        # PID
        self.pid = PIDControl(
            self.manager,
            lambda value: self.bridge.change_control(f"beam.{beam.name}.offset", value),
            lambda value: self.bridge.change_control(f"beam.{beam.name}.y", value),
            lambda p, i, gl: self.bridge.set_beam_iir(beam.name, p, i, gl),
            ch=channel,
        )
        self.tabs.addTab(self.pid, "PID")

        # Booster
        self.booster = BoosterControl(boostermanager, self.set_tab, ch=channel)
        self.tabs.addTab(self.booster, "Booster")
        if beam.name in {"CDT1", "CDT2"}:
            self.tabs.addTab(self.pulse, "Pulse")

        vbox.addWidget(self.tabs)

    def start_pulsing(self):
        if self._pulse_running:
            self.stop_pulsing()
            return
        self._pulse_running = True
        self._pulse_on_time = self.pulse_on_time.value() * ms
        self._pulse_off_time = self.pulse_off_time.value() * ms
        period = self._pulse_on_time + self._pulse_off_time
        self._pulse_batch_count = max(1, min(10000, int(1.0 / period)))
        self.pulse_button.setText("Stop pulsing")
        self.pulse_on_time.setEnabled(False)
        self.pulse_off_time.setEnabled(False)
        self.dds_button.setEnabled(False)
        self.pid_button.setEnabled(False)
        self._emit_next_pulse()

    def _emit_next_pulse(self):
        if not self._pulse_running:
            return
        try:
            self.bridge.pulse_beam(
                self.beam.name,
                self._pulse_on_time,
                self._pulse_off_time,
                self._pulse_batch_count,
            )
        except Exception as error:
            logging.getLogger(__name__).exception("SUServo pulse failed")
            QMessageBox.critical(self, "SUServo pulse failed", str(error))
            self.stop_pulsing()
            return

        if self._pulse_running:
            # Yield to the event loop so Stop pulsing can be handled between batches.
            self._pulse_timer.start(1)
        else:
            self.stop_pulsing()

    def stop_pulsing(self):
        self._pulse_running = False
        self._pulse_timer.stop()
        self.pulse_button.setEnabled(True)
        self.pulse_button.setText("Start pulsing")
        self.pulse_on_time.setEnabled(True)
        self.pulse_off_time.setEnabled(True)
        self.dds_button.setEnabled(True)
        self.pid_button.setEnabled(True)

    def set_tab(self, index):
        self.tabs.setCurrentIndex(index)

    def refresh(self):
        self.dds_button.set_state(self.manager.en_outs[self.channel])
        self.pid_button.set_state(self.manager.en_iirs[self.channel])
        self.dds.refresh()
        self.pid.refresh()

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox


class SingleChannelMirny(QWidget):
    """Class to control a single given Mirny channel
    NB this is an on button for the channel and a
    freq/att/on off control much like the SUServo DDS panel
    """

    def __init__(self, manager, bridge, eom, channel=0):
        # manager : MirnyManager
        QWidget.__init__(self)
        self.manager = manager
        self.channel = channel
        self.eom = eom
        self.bridge = bridge

        self.groupbox = QGroupBox()

        # Stack all other widgets vertically
        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # Top row: ON/OFF switch, almazny on/off, channel name
        # ON/OFF switch {{{
        top = QHBoxLayout()
        self.dds_button = Switch(
            default=self.manager.en_outs[channel],
            turn_on=lambda: self.bridge.change_control(
                f"eom.{eom.name}.output_enabled", True
            ),
            turn_off=lambda: self.bridge.change_control(
                f"eom.{eom.name}.output_enabled", False
            ),
            on_text="Mirny",
            off_text="Mirny",
        )
        top.addWidget(self.dds_button)

        self.almazny_button = Switch(
            default=self.manager.en_almazny[channel],
            turn_on=lambda: self.bridge.change_control(
                f"eom.{eom.name}.almazny_enabled", True
            ),
            turn_off=lambda: self.bridge.change_control(
                f"eom.{eom.name}.almazny_enabled", False
            ),
            on_text="Almazny",
            off_text="Almazny",
        )
        top.addWidget(self.almazny_button)

        top.addStretch()

        # Channel name
        name = QLabel(eom.name)
        name.setStyleSheet("font: bold 12pt")
        top.addWidget(name)

        vbox.addLayout(top)

        # DDS
        self.dds = DDSControl(
            self.manager,
            lambda value: (
                self.bridge.change_control(f"eom.{eom.name}.frequency", value * MHz)
                / MHz
            ),
            lambda value: self.bridge.change_control(
                f"eom.{eom.name}.attenuation", value
            ),
            ch=channel,
            minimum=53.125,
            maximum=6800.0,
        )
        # tabs.addTab(freq, "DDS")

        vbox.addWidget(self.dds)

        # note that almazny is double the frequency of mirny
        # center label
        hhbox = QHBoxLayout()
        hhbox.addStretch()
        almazny_freq = QLabel("Almazny is 2x Mirny")
        hhbox.addWidget(almazny_freq)
        hhbox.addStretch()
        vbox.addLayout(hhbox)

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox

    def refresh(self):
        self.dds_button.set_state(self.manager.en_outs[self.channel])
        self.almazny_button.set_state(self.manager.en_almazny[self.channel])
        self.dds.refresh()


class SUServoGUI(QWidget):
    def __init__(self, manager, bridge):
        super().__init__()
        self.manager = manager
        self.bridge = bridge
        self.setGeometry(self.x(), self.y(), self.minimumWidth(), self.minimumHeight())
        self.booster = BoosterTelemetry(self.update_booster)
        self.booster.set_telem_period(1)
        self.ch = [
            SingleChannelSUServo(self.manager, self.bridge, self.booster, beam, i)
            for i, beam in enumerate(self.manager.beams)
        ]

        self.setWindowTitle("SUServo GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Artiq status {{{
        hbox = QHBoxLayout()
        hbox.addStretch()
        self.servo_button = Switch(
            self.manager.enabled,
            lambda: self.bridge.change_control("suservo.enabled", True),
            lambda: self.bridge.change_control("suservo.enabled", False),
        )
        hbox.addWidget(self.servo_button)
        self.label = QLabel("SUServo")  # Bold large text
        self.label.setStyleSheet("font: bold 14pt")
        hbox.addWidget(self.label)
        hbox.addStretch()

        shutterlabel = QLabel("Shutters")
        shutterlabel.setStyleSheet("font: bold 14pt")
        hbox.addWidget(shutterlabel)
        self.shutter_buttons = []
        for ch, shutter in enumerate(self.manager.shutter_infos):
            if shutter.name in FlipMirrorGUI.FLIP_MIRROR_NAMES:
                continue
            shutter_button = Switch(
                default=self.manager.en_shutters[ch],
                turn_on=lambda name=shutter.name: self.bridge.change_control(
                    f"shutter.{name}.open", True
                ),
                turn_off=lambda name=shutter.name: self.bridge.change_control(
                    f"shutter.{name}.open", False
                ),
                on_text=shutter.name,
                off_text=shutter.name,
            )
            self.shutter_buttons.append(shutter_button)
            hbox.addWidget(shutter_button)
        layout.addLayout(hbox)
        # }}}

        # Create channels controls
        chans = QGridLayout()
        for i, channel in enumerate(self.ch):
            chans.addWidget(channel.get_widget(), i % 4, i // 4)
        layout.addLayout(chans)

        # capture the keyboard numbers to enable/disable channels
        self.installEventFilter(self)
        self.bridge.state_changed.connect(self.refresh)

    def eventFilter(self, obj, event):
        if (
            event.type() == event.KeyPress
            and event.key() >= Qt.Key_0
            and event.key() < Qt.Key_0 + len(self.ch)
        ):
            # just click the button for the channel to avoid implementing any logic here
            if QApplication.keyboardModifiers() == Qt.ControlModifier:
                self.ch[event.key() - Qt.Key_0].pid_button.switch_state()
            else:
                self.ch[event.key() - Qt.Key_0].dds_button.switch_state()
            return 1
        return super().eventFilter(obj, event)

    def update_booster(self, ch, data):
        self.ch[ch].booster.update(json.loads(data))

    def refresh(self, _state=None):
        self.servo_button.set_state(self.manager.enabled)
        for channel in self.ch:
            channel.refresh()
        for index, button in enumerate(self.shutter_buttons):
            button.set_state(self.manager.en_shutters[index])


class MirnyGUI(QWidget):
    def __init__(self, manager, bridge):
        super().__init__()
        self.manager = manager
        self.bridge = bridge
        self.ch = [
            SingleChannelMirny(self.manager, self.bridge, eom, channel)
            for eom, channel in zip(self.manager.eoms, self.manager.eom_channels)
        ]

        self.setWindowTitle("Mirny GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # create channels controls
        chans = QGridLayout()
        for i, channel in enumerate(self.ch):
            chans.addWidget(channel.get_widget(), i, 0)
        layout.addLayout(chans)

        # capture the keyboard numbers to enable/disable channels
        self.installEventFilter(self)
        self.bridge.state_changed.connect(self.refresh)

    def refresh(self, _state=None):
        for channel in self.ch:
            channel.refresh()

    def eventFilter(self, obj, event):
        if (
            event.type() == event.KeyPress
            and event.key() >= Qt.Key_0
            and event.key() < Qt.Key_0 + len(self.ch)
        ):
            # just click the button for the channel to avoid implementing any logic here
            if QApplication.keyboardModifiers() == Qt.ControlModifier:
                self.ch[event.key() - Qt.Key_0].almazny_button.switch_state()
            else:
                self.ch[event.key() - Qt.Key_0].dds_button.switch_state()
            return 1
        return super().eventFilter(obj, event)


class FlipMirrorGUI(QWidget):
    """Small standalone window for the two ODT flip mirrors."""

    FLIP_MIRROR_NAMES = (
        "ODT Dimple flip mirror",
        "ODT Res flip mirror",
    )

    def __init__(self, manager, bridge):
        super().__init__()
        self.manager = manager
        self.bridge = bridge
        shutter_indices = {
            shutter.name: index for index, shutter in enumerate(manager.shutter_infos)
        }
        missing = [
            name for name in self.FLIP_MIRROR_NAMES if name not in shutter_indices
        ]
        if missing:
            raise ValueError(f"Flip mirror shutters are not configured: {missing}")

        self.shutter_indices = [
            shutter_indices[name] for name in self.FLIP_MIRROR_NAMES
        ]
        self.buttons = []
        self._warnings = []
        layout = QVBoxLayout(self)
        for name, channel in zip(self.FLIP_MIRROR_NAMES, self.shutter_indices):
            row = QHBoxLayout()
            label = QLabel(name)
            label.setStyleSheet("font: bold 11pt")
            row.addWidget(label)

            button = Switch(
                default=manager.en_shutters[channel],
                turn_on=lambda shutter_name=name: self._set_mirror(shutter_name, True),
                turn_off=lambda shutter_name=name: self._set_mirror(
                    shutter_name, False
                ),
                on_text="Beam blocked",
                off_text="Beam unblocked",
                colors=[
                    "background-color: #5db75d",
                    "background-color: #b75d5d",
                ],
            )
            button.button.setToolTip(
                "Inserted mirror diverts the beam to the coupler (blocked from the experiment)."
                if manager.en_shutters[channel]
                else "Mirror is retracted; the beam path to the experiment is unblocked."
            )
            self.buttons.append(button)
            row.addWidget(button)
            layout.addLayout(row)

        self.setWindowTitle("ODT Flip Mirrors")
        bridge.state_changed.connect(self.refresh)

    def _set_mirror(self, name, enabled):
        if not enabled:
            self._show_unblocked_beam_warning(name)
        try:
            return self.bridge.change_control(f"shutter.{name}.open", enabled)
        except Exception as error:
            logging.getLogger(__name__).exception("Flip-mirror switch failed")
            QMessageBox.critical(self, "Flip-mirror switch failed", str(error))
            return bool(
                self.manager.en_shutters[
                    self.shutter_indices[self.FLIP_MIRROR_NAMES.index(name)]
                ]
            )

    def _show_unblocked_beam_warning(self, name):
        warning = QMessageBox(self)
        warning.setIcon(QMessageBox.Warning)
        warning.setWindowTitle("Beam path warning")
        warning.setText(f"Retracting {name} unblocks the beam path to the experiment.")
        warning.setStandardButtons(QMessageBox.Ok)
        warning.setModal(False)
        warning.setAttribute(Qt.WA_DeleteOnClose)
        self._warnings.append(warning)
        warning.finished.connect(
            lambda _result, dialog=warning: (
                self._warnings.remove(dialog) if dialog in self._warnings else None
            )
        )
        warning.show()

    def refresh(self, _state=None):
        for button, channel in zip(self.buttons, self.shutter_indices):
            blocked = bool(self.manager.en_shutters[channel])
            button.set_state(blocked)
            button.button.setToolTip(
                "Inserted mirror diverts the beam to the coupler (blocked from the experiment)."
                if blocked
                else "Mirror is retracted; the beam path to the experiment is unblocked."
            )


class ArtiqGUIExperiment(EnvExperiment):
    """Artiq GUI"""

    def build(self):
        self.core: Core = self.get_device("core")

        self.setattr_argument(
            "remoteDisplay",
            BooleanValue(False),
            group="GUI",
            tooltip="Enable remote X forwarded display",
        )

        self.setattr_argument(
            "display",
            StringValue("127.0.0.1:11.0"),
            group="GUI",
            tooltip="The remote X forwarded display",
        )

        self.suservo = self.get_device("suservo")
        self.suservo_beams = configured_in_channel_order(
            SUSERVOED_BEAMS.values(), "suservo_device", "suservo_ch"
        )
        self.suservo_chs = [
            self.get_device(beam.suservo_device) for beam in self.suservo_beams
        ]
        self.shutter_infos = list(SHUTTERS.values())
        self.shutters = [self.get_device(shutter.ttl) for shutter in self.shutter_infos]
        self.suservoManager: SUServoManager

        self.eoms = configured_in_channel_order(EOMS.values(), "mirny_ch", "mirny_ch")
        self.eom_channels = [
            logical_channel(eom.mirny_ch, "mirny_ch") for eom in self.eoms
        ]
        self.mirny_chs = [
            self.get_device(name) for name in physical_channel_aliases("mirny_ch")
        ]
        self.almazny = [
            self.get_device(name) for name in physical_channel_aliases("almazny_ch")
        ]
        self.mirnyManager: MirnyManager

        self.fastino = self.get_device("fastino")
        self.vdrivenSupplyManager: VDrivenSupplyManager

    def run(self):
        # Startups run methods
        self.core.reset()

        if self.remoteDisplay:
            self.find_working_display()

        # SUServo
        self.suservoManager = SUServoManager(
            self,
            self.core,
            self.suservo,
            self.suservo_chs,
            self.shutters,
            self.suservo_beams,
            self.shutter_infos,
        )

        # Mirny
        self.mirnyManager = MirnyManager(
            self,
            self.core,
            self.mirny_chs,
            self.almazny,
            self.eoms,
            self.eom_channels,
        )

        # Voltage-driven supplies. devices.py is the source of truth for names,
        # channels, gains, limits, units and disabled state.
        self.vdrivenSupplyManager = VDrivenSupplyManager(
            self,
            self.core,
            self.fastino,
            list(VDRIVEN_SUPPLIES.values()),
            name="fastino",
        )

        # now ours
        app = QApplication(sys.argv)
        # Set a nice icon
        app.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/do.png"))
        app.setStyle("Fusion")
        app.setApplicationName("ARTIQ GUI")

        bridge = GuiControlBridge(
            self.suservoManager,
            self.mirnyManager,
            self.vdrivenSupplyManager,
        )

        suservoGUI = SUServoGUI(self.suservoManager, bridge)
        suservoGUI.show()

        mirnyGUI = MirnyGUI(self.mirnyManager, bridge)
        mirnyGUI.show()

        flipMirrorGUI = FlipMirrorGUI(self.suservoManager, bridge)
        flipMirrorGUI.show()

        vdrivenGUI = VDrivenSuppliesGUI(self.vdrivenSupplyManager, bridge)
        vdrivenGUI.show()

        adapter = GuiControlAdapter(bridge)
        try:
            adapter.start()
        except OSError:
            logging.getLogger(__name__).exception(
                "Could not start the loopback GUI control adapter"
            )
        else:
            app.aboutToQuit.connect(adapter.stop)
        try:
            app.exec_()
        finally:
            adapter.stop()

    @rpc
    def find_working_display(self):
        import subprocess

        os.environ.pop("XAUTHORITY", None)

        os.environ["DISPLAY"] = self.display
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from PyQt5.QtWidgets import QApplication;app = QApplication([])",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            return True
        raise RuntimeError(
            "Could not find a working display localhost:10 to localhost:15"
            " - Ensure localhost is set to 127.0.0.1 in /etc/hosts"
            " - check `xmessage -center 'hello world'` works"
            " - if you are running locally, set remoteDisplay to False"
        )
