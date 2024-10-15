##########################################################################################
# Instructions to use:
#       - go to the same directory as the 'device.db' file
#           (otherwise you must specify the correct --device-db)
#       - run this file as `artiq_run dds_control_interface.py`
#      [-] specify `--device-db path/to/device.db` parameter with proper path if needed
#      [-] add a & to the end of the call to run as a background process
##########################################################################################

import sys
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
    QComboBox,
    QTabWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QIntValidator
from repository.utils.SUServoManager import SUServoManager
from repository.utils.MirnyManager import MirnyManager

from artiq.experiment import *
from artiq.language import MHz, ms


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
        self.text.setText(str(round(self.manager.freqs[ch] / MHz, 3)))
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
        self.slider.setValue(int(self.manager.freqs[ch] / MHz))
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
        except:
            self.text.setText(str(self.slider.value()))
            return

        # guard against recursion already at the correct frequency
        if val == self.manager.freqs[self.ch] / MHz:
            return

        val = min(max(val, self.min), self.max)
        self.text.setText(str(val))
        self.slider.setValue(int(val))

        self.manager.set_freq(self.ch, val)


class PIDControl(QWidget):
    def __init__(self, manager, ch=0):
        super().__init__()
        self.manager = manager
        self.en_out = self.manager.en_outs[ch]
        self.ch = ch

        layout = QVBoxLayout()

        # Enable button
        top = QHBoxLayout()
        # Sampler channel 0-7 (picker)
        sampler_label = QLabel("Sampler")
        top.addWidget(sampler_label)
        self.sampler = QComboBox()
        self.sampler.addItems([str(i) for i in range(8)])
        self.sampler.setCurrentIndex(self.manager.sampler_chs[ch])
        self.sampler.currentIndexChanged.connect(lambda: self.set())
        top.addWidget(self.sampler)
        # Setpoint -1 to 1 linedit
        setpoint_label = QLabel("Setpoint")
        top.addWidget(setpoint_label)
        self.setpoint = QLineEdit()
        self.setpoint.setText(str(self.manager.ys[ch]))
        self.setpoint.setValidator(QDoubleValidator(-1.00, 1.00, 3))
        self.setpoint.editingFinished.connect(lambda: self.set())
        top.addWidget(self.setpoint)
        # Gain
        gain_label = QLabel("Gain")
        top.addWidget(gain_label)
        self.gain = QLineEdit()
        self.gain.setText(str(self.manager.gains[ch]))
        self.gain.setValidator(QIntValidator(0, 3))
        self.gain.editingFinished.connect(
            lambda: self.manager.set_gain(ch, int(self.gain.text()))
        )
        top.addWidget(self.gain)

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
        i_box = QHBoxLayout()
        I_label = QLabel("I")
        bottom.addWidget(I_label)
        self.I = QLineEdit()
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
            int(self.sampler.currentIndex()),
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

    def __init__(self, manager, channel=0):
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
        name = QLabel(f"Ch {channel}")
        name.setStyleSheet("font: bold 12pt")
        top.addWidget(name)

        vbox.addLayout(top)

        # Initialize tab screen
        tabs = QTabWidget()

        # DDS
        freq = DDSControl(self.manager, ch=channel, minimum=0.0, maximum=400.0)
        tabs.addTab(freq, "DDS")

        # PID
        pid = PIDControl(self.manager, ch=channel)
        tabs.addTab(pid, "PID")

        # GRAPH
        # TODO: Add graphing functionality
        scope = QLabel("")
        tabs.addTab(scope, "Scope")

        vbox.addWidget(tabs)

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox


class SingleChannelMirny(QWidget):
    """Class to control a single given Mirny channel
    NB this is an on button for the channel and a freq/att/on off control much like the SUServo DDS panel
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
        name = QLabel(f"Ch {channel}")
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
        almazny_freq = QLabel(f"Almazny is 2x Mirny")
        hhbox.addWidget(almazny_freq)
        hhbox.addStretch()
        vbox.addLayout(hhbox)

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox


class SUServoGUI(QWidget):  # {{{
    def __init__(self, experiment, core, suservo, suservo_chs):
        super().__init__()
        self.setGeometry(self.x(), self.y(), self.minimumWidth(), self.minimumHeight())
        self.manager = SUServoManager(experiment, core, suservo, suservo_chs)
        self.ch = [SingleChannelSUServo(self.manager, i) for i in range(8)]

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
        layout.addLayout(hbox)
        # }}}

        # Create channels controls
        chans = QGridLayout()
        for i in range(8):
            chans.addWidget(self.ch[i].get_widget(), i % 4, i // 4)
        layout.addLayout(chans)


# }}}
class MirnyGUI(QWidget):

    def __init__(self, experiment, core, mirny_chs, almazny):
        super().__init__()
        self.manager = MirnyManager(experiment, core, mirny_chs, almazny)
        self.ch = [SingleChannelMirny(self.manager, i) for i in range(4)]

        self.setWindowTitle("Mirny GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # create channels controls
        chans = QGridLayout()
        for i in range(4):
            chans.addWidget(self.ch[i].get_widget(), i, 0)
        layout.addLayout(chans)


class ArtiqGUIExperiment(EnvExperiment):  # {{{
    """Artiq GUI"""

    def build(self):
        self.core = self.get_device("core")
        self.suservo = self.get_device("suservo")
        self.suservo_chs = [self.get_device(f"suservo_ch{i}") for i in range(8)]
        self.mirny_chs = [self.get_device(f"mirny_ch{i}") for i in range(4)]
        self.almazny = [self.get_device(f"almazny_ch{i}") for i in range(4)]

    def run(self):
        self.init_kernel()
        app = QApplication(sys.argv)

        screen = SUServoGUI(self, self.core, self.suservo, self.suservo_chs)
        screen.show()

        screen2 = MirnyGUI(self, self.core, self.mirny_chs, self.almazny)
        screen2.setGeometry(
            screen.x() + screen.minimumWidth(),
            screen.y(),
            screen.minimumWidth() // 2,
            screen.minimumHeight(),
        )
        screen2.show()

        app.exec_()

    @kernel
    def init_kernel(self):
        """Initialize core"""
        self.core.reset()


# }}}
