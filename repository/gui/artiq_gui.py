import sys
import os
import json
from PyQt5.QtWidgets import (
    QWidget,
    QGroupBox,
    QVBoxLayout,
    QPushButton,
    QDoubleSpinBox,
    QGridLayout,
    QApplication,
    QLabel,
    QHBoxLayout,
    QLineEdit,
    QSlider,
    QTabWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QIcon
from PyQt5.QtCore import QTimer


sys.path.append(os.path.abspath(os.path.dirname(__file__)))
# disable formatting
# flake8: noqa
from managers.SUServoManager import SUServoManager
from managers.boosterTelemetry import BoosterTelemetry
from managers.MirnyManager import MirnyManager
from managers.FastinoManager import FastinoManager, DeltaElektronikaManager

from artiq.coredevice.core import Core

from artiq.experiment import kernel, EnvExperiment, rpc
from artiq.language import ms, BooleanValue

class Switch(QWidget):
    def __init__(self, default: bool, turn_on, turn_off, on_text="ON", off_text="OFF"):
        super().__init__()
        self.turn = [turn_on, turn_off]
        self.state = default
        self.text = [off_text, on_text]
        self.color = ["background-color: #b75d5d", "background-color: #5db75d"]
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
        self.turn[self.state]()  # Swap state
        self.state = not self.state

        self.button.setText(self.text[self.state])  # Change text and color
        self.button.setStyleSheet(self.color[self.state])


class SignalDoubleSpinBox(QDoubleSpinBox):
    stepChanged = pyqtSignal()

    def stepBy(self, step):
        value = self.value()
        super(QDoubleSpinBox, self).stepBy(step)
        if self.value() != value:
            self.stepChanged.emit()


class DDSControl(QWidget):
    def __init__(self, manager, ch=0, minimum=0.0, maximum=400.0):
        super().__init__()
        self.min = minimum
        self.max = maximum
        self.manager = manager
        self.ch = ch

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

        att_input = SignalDoubleSpinBox()
        att_input.setRange(0.0, 31.5)
        att_input.setSingleStep(0.5)
        att_input.setDecimals(1)
        att_input.setValue(self.manager.atts[ch])
        att_input.setSuffix(" dB")
        att_input.editingFinished.connect(
            lambda: self.manager.set_att(ch, att_input.value())
        )
        att_input.stepChanged.connect(
            lambda: self.manager.set_att(ch, att_input.value())
        )

        inputline = QHBoxLayout()
        inputline.addWidget(self.text)
        inputline.addStretch()
        inputline.addWidget(att_input)
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
        self.slider.setValue(int(val))

        self.manager.set_freq(self.ch, val)


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
    def __init__(self, manager, ch=0):
        super().__init__()
        self.manager: SUServoManager = manager
        self.en_out = self.manager.en_outs[ch]
        self.ch = ch

        layout = QVBoxLayout()

        top = QHBoxLayout()
        top.addWidget(QLabel("Target (V)"))
        self.setpoint = QLineEdit()
        self.setpoint.setText(str(self.manager.offsets[ch]))
        self.setpoint.setValidator(QDoubleValidator(-10.00, 10.00, 10))
        self.setpoint.editingFinished.connect(
            lambda: self.manager.set_offset(ch, float(self.setpoint.text()))
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
                    pow = f"{power if power >= 0.1 else power*1e3:.1f} \
                        <b>{'mW' if power >= 0.1 else 'uW'}</b>"
                self.adc_val.setText(
                    f"{pow} | {volt:.2f} <b>V</b> | \
                        {self.manager.get_y(ch)*100:.0f}%"
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
        amp_input = SignalDoubleSpinBox()
        amp_input.setRange(0.0, 1.0)
        amp_input.setSingleStep(0.1)
        amp_input.setDecimals(1)
        amp_input.setValue(self.manager.ys[ch])
        amp_input.editingFinished.connect(
            lambda: self.manager.set_y(ch, amp_input.value())
        )
        amp_input.stepChanged.connect(lambda: self.manager.set_y(ch, amp_input.value()))
        amp_vbox.addWidget(amp_input)
        bottom.addLayout(amp_vbox)

        layout.addLayout(bottom)
        self.setLayout(layout)

    def set(self):
        self.manager.set_iir(
            self.ch,
            self.ch,
            float(self.P.text()),
            float(self.I.text()),
            float(self.Gl.text()),
        )


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

    def __init__(self, manager, boostermanager, channel=0):
        # manager : SUServoManager
        QWidget.__init__(self)
        self.manager = manager
        self.channel = channel

        self.groupbox = QGroupBox()

        # Stack all other widgets vertically
        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # Top row: ON/OFF switch, PID switch, channel name
        # ON/OFF switch {{{
        top = QHBoxLayout()
        self.dds_button = Switch(
            default=self.manager.en_outs[channel],
            turn_on=lambda: self.manager.enable(channel),
            turn_off=lambda: self.manager.disable(channel),
        )
        top.addWidget(self.dds_button)
        self.pid_button = Switch(
            default=self.manager.en_iirs[channel],
            turn_on=lambda: self.manager.enable_iir(channel),
            turn_off=lambda: self.manager.disable_iir(channel),
            on_text="PID",
            off_text="PID",
        )
        top.addWidget(self.pid_button)
        # }}}

        top.addStretch()

        # Channel name
        channelsMap = ["LOCK", "MOT", "IMG", "PUMP", "852 X", "852 Y", "CDT 1", "CDT 2"]
        name = QLabel(f"Ch {channel} - ({channelsMap[channel]})")
        name.setStyleSheet("font: bold 12pt")
        top.addWidget(name)

        vbox.addLayout(top)

        # Initialize tab screen
        self.tabs = QTabWidget()

        # DDS
        freq = DDSControl(self.manager, ch=channel, minimum=0.0, maximum=400.0)
        self.tabs.addTab(freq, "DDS")

        # PID
        pid = PIDControl(self.manager, ch=channel)
        self.tabs.addTab(pid, "PID")

        # Booster
        self.booster = BoosterControl(boostermanager, self.set_tab, ch=channel)
        self.tabs.addTab(self.booster, "Booster")

        vbox.addWidget(self.tabs)

    def set_tab(self, index):
        self.tabs.setCurrentIndex(index)

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox


class SingleChannelMirny(QWidget):
    """Class to control a single given Mirny channel
    NB this is an on button for the channel and a
    freq/att/on off control much like the SUServo DDS panel
    """

    def __init__(self, manager, channel=0):
        # manager : MirnyManager
        QWidget.__init__(self)
        self.manager = manager
        self.channel = channel

        self.groupbox = QGroupBox()

        # Stack all other widgets vertically
        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # Top row: ON/OFF switch, almazny on/off, channel name
        # ON/OFF switch {{{
        top = QHBoxLayout()
        self.dds_button = Switch(
            default=self.manager.en_outs[channel],
            turn_on=lambda: self.manager.enable(channel),
            turn_off=lambda: self.manager.disable(channel),
            on_text="Mirny",
            off_text="Mirny",
        )
        top.addWidget(self.dds_button)

        self.almazny_button = Switch(
            default=self.manager.en_almazny[channel],
            turn_on=lambda: self.manager.enable_almazny(channel),
            turn_off=lambda: self.manager.disable_almazny(channel),
            on_text="Almazny",
            off_text="Almazny",
        )
        top.addWidget(self.almazny_button)

        top.addStretch()

        # Channel name
        name = QLabel(["Ch 0 - (EOM)", "Ch 1", "Ch 2", "Ch 3"][channel])
        name.setStyleSheet("font: bold 12pt")
        top.addWidget(name)

        vbox.addLayout(top)

        # DDS
        freq = DDSControl(self.manager, ch=channel, minimum=53.125, maximum=6800.0)
        # tabs.addTab(freq, "DDS")

        vbox.addWidget(freq)

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


class SUServoGUI(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setGeometry(self.x(), self.y(), self.minimumWidth(), self.minimumHeight())
        self.booster = BoosterTelemetry(self.update_booster)
        self.booster.set_telem_period(1)
        self.ch = [
            SingleChannelSUServo(self.manager, self.booster, i) for i in range(8)
        ]

        self.setWindowTitle("SUServo GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Artiq status {{{
        hbox = QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(
            Switch(
                self.manager.enabled,
                self.manager.enable_servo,
                self.manager.disable_servo,
            )
        )
        self.label = QLabel("SUServo")  # Bold large text
        self.label.setStyleSheet("font: bold 14pt")
        hbox.addWidget(self.label)
        hbox.addStretch()

        shutterlabel = QLabel("Shutters")
        shutterlabel.setStyleSheet("font: bold 14pt")
        hbox.addWidget(shutterlabel)
        for ch, name in enumerate(["2DMOT", "3DMOT", "IMG", "LATTICE"]):
            self.shutter_button = Switch(
                default=self.manager.en_shutters[ch],
                turn_on=lambda channel=ch: self.manager.open_shutter(channel),
                turn_off=lambda channel=ch: self.manager.close_shutter(channel),
                on_text=name,
                off_text=name,
            )
            hbox.addWidget(self.shutter_button)
        layout.addLayout(hbox)
        # }}}

        # Create channels controls
        chans = QGridLayout()
        for i in range(8):
            chans.addWidget(self.ch[i].get_widget(), i % 4, i // 4)
        layout.addLayout(chans)

        # capture the keyboard numbers to enable/disable channels
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            event.type() == event.KeyPress
            and event.key() >= Qt.Key_0
            and event.key() <= Qt.Key_7
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


class MirnyGUI(QWidget):

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.ch = [SingleChannelMirny(self.manager, i) for i in range(4)]

        self.setWindowTitle("Mirny GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # create channels controls
        chans = QGridLayout()
        for i in range(1):
            chans.addWidget(self.ch[i].get_widget(), i, 0)
        layout.addLayout(chans)

        # capture the keyboard numbers to enable/disable channels
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            event.type() == event.KeyPress
            and event.key() >= Qt.Key_0
            and event.key() <= Qt.Key_3
        ):
            # just click the button for the channel to avoid implementing any logic here
            if QApplication.keyboardModifiers() == Qt.ControlModifier:
                self.ch[event.key() - Qt.Key_0].almazny_button.switch_state()
            else:
                self.ch[event.key() - Qt.Key_0].dds_button.switch_state()
            return 1
        return super().eventFilter(obj, event)


class SingleChannelFastino(QWidget):
    def __init__(
        self,
        manager: FastinoManager,
        ch=0,
        name="Ch",
        getter=None,
        setter=None,
        min=None,
        max=None,
    ):
        super().__init__()
        self.manager = manager
        self.ch = ch

        self.getter = getter if getter is not None else self.manager.get_voltage
        self.setter = setter if setter is not None else self.manager.set_voltage

        self.MIN = min if min is not None else self.manager.MIN
        self.MAX = max if max is not None else self.manager.MAX

        self.enabled = self.getter(self.ch) != 0.0

        self.groupbox = QGroupBox()

        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # labels
        labelline = QHBoxLayout()

        self.button = Switch(
            default=self.enabled,
            turn_on=self.switch_on,
            turn_off=self.switch_off,
            on_text="ON",
            off_text="OFF",
        )
        labelline.addWidget(self.button)

        labelline.addStretch()
        # Channel name
        self.name = QLabel(name)
        self.name.setStyleSheet("font: bold 12pt")
        labelline.addWidget(self.name)
        vbox.addLayout(labelline)

        # text inputs
        self.text = QLineEdit()
        self.text.setText(str(round(self.getter(self.ch), 3)))
        self.text.setValidator(QDoubleValidator())
        self.text.setAlignment(Qt.AlignCenter)
        self.text.editingFinished.connect(lambda: self.set(self.text.text()))

        inputline = QHBoxLayout()
        inputline.addWidget(self.text)
        vbox.addLayout(inputline)

        # Slider and min/max labels
        min_label = QLabel(f"{round(self.MIN)} <b>{self.manager.unit}</b>")
        max_label = QLabel(f"{round(self.MAX)} <b>{self.manager.unit}</b>")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setSingleStep(10)
        self.slider.setRange(int(self.MIN * 1000), int(self.MAX * 1000))
        self.slider.setValue(int(self.getter(ch) * 1000))
        self.slider.valueChanged.connect(lambda x: self.set(x / 1000))

        sliderline = QHBoxLayout()
        sliderline.addWidget(min_label)
        sliderline.addWidget(self.slider)
        sliderline.addWidget(max_label)

        vbox.addLayout(sliderline)

    def set(self, val, force=False):
        # check its a valid number - if not the text edit went wrong
        try:
            val = float(val)
        except ValueError:
            self.text.setText(str(self.slider.value() / 1000))
            return

        # guard against recursion already at the correct voltage
        if val == round(self.getter(self.ch), 3) and not force:
            return

        val = min(max(val, self.MIN), self.MAX)
        self.text.setText(str(val))
        self.slider.setValue(int(val * 1000))

        if self.enabled:
            self.setter(self.ch, float(val))

    def switch_on(self):
        self.enabled = True
        self.set(self.text.text())
        return

    def switch_off(self):
        self.enabled = False
        self.setter(self.ch, 0.0)
        return

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox


class FastinoGUI(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

        self.setWindowTitle("Fastino GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Create control for 8 DACs
        chans = QGridLayout()
        self.ch = [
            SingleChannelFastino(
                self.manager,
                i,
                f"Ch {i}",
            )
            for i in range(8)
        ]

        chans = QGridLayout()
        for i in range(8):
            chans.addWidget(self.ch[i].get_widget(), i % 4, i // 4)
        layout.addLayout(chans)


class DeltaElektronikaGUI(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

        self.setWindowTitle("Delta Elektronika GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Create control for 8 DACs
        chans = QGridLayout()
        self.ch = [
            SingleChannelFastino(
                self.manager,
                i,
                ["Ch 0 (X1)", "Ch 1 (X2)", "Ch 2 (Y)", "Ch 3 (Z)"][i],
                getter=self.manager.get_current,
                setter=self.manager.set_current,
                min=0.0,
                max=2.0,
            )
            for i in range(4)
        ]

        chans = QGridLayout()
        for i in range(4):
            chans.addWidget(self.ch[i].get_widget(), i % 2, i // 2)
        layout.addLayout(chans)


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

        self.suservo = self.get_device("suservo")
        self.suservo_chs = [self.get_device(f"suservo_ch{i}") for i in range(8)]
        self.shutters = [
            self.get_device("shutter_2DMOT"),
            self.get_device("shutter_3DMOT"),
            self.get_device("shutter_IMG"),
            self.get_device("shutter_LATTICE"),
        ]
        self.suservoManager: SUServoManager

        self.mirny_chs = [self.get_device(f"mirny_ch{i}") for i in range(4)]
        self.almazny = [self.get_device(f"almazny_ch{i}") for i in range(4)]
        self.mirnyManager: MirnyManager

        self.fastino = self.get_device("fastino")
        self.useFastino = False
        self.fastinoManager: FastinoManager
        self.deltaElektronikaManager: DeltaElektronikaManager

    def run(self):
        # Startups run methods
        self.core.reset()

        if self.remoteDisplay:
            self.find_working_display()

        # SUServo
        self.suservoManager = SUServoManager(
            self, self.core, self.suservo, self.suservo_chs, self.shutters
        )

        # Mirny
        self.mirnyManager = MirnyManager(self, self.core, self.mirny_chs, self.almazny)

        # Fastino
        if self.useFastino:
            self.fastinoManager = FastinoManager(self, self.core, self.fastino)
        else:
            self.deltaElektronikaManager = DeltaElektronikaManager(
                self, self.core, self.fastino
            )

        # now ours
        app = QApplication(sys.argv)
        # Set a nice icon
        app.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/do.png"))
        app.setStyle("Fusion")
        app.setApplicationName("ARTIQ GUI")

        suservoGUI = SUServoGUI(self.suservoManager)
        suservoGUI.show()

        mirnyGUI = MirnyGUI(self.mirnyManager)
        mirnyGUI.show()

        if self.useFastino:
            fastinoGUI = FastinoGUI(self.fastinoManager)
            fastinoGUI.show()
        else:
            deltaGUI = DeltaElektronikaGUI(self.deltaElektronikaManager)
            deltaGUI.show()

        app.exec_()

    @rpc
    def find_working_display(self):
        import subprocess

        os.environ.pop("XAUTHORITY", None)

        for num in range(10, 15):
            os.environ["DISPLAY"] = f"localhost:{num}"
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
                print(f"Connected to display localhost:{num}")
                return True
        raise RuntimeError(
            "Could not find a working display localhost:10 to localhost:15"
            " - check your X forwarding settings"
            " - if you are running locally, set remoteDisplay to False"
        )
