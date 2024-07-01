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
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator, QIntValidator
from repository.utils.SUServoManager import SUServoManager

from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel


class Switch(QWidget):
    def __init__(self, default: bool, turn_on, turn_off, on_text="ON", off_text="OFF"):
        super().__init__()
        self.turn_on = turn_on
        self.turn_off = turn_off
        self.state = default
        self.text = [off_text, on_text]

        # Main layout for this widget
        layout = QVBoxLayout()

        self.button = QPushButton()
        self.button.setText(self.text[default])
        self.button.setCheckable(True)
        self.button.setStyleSheet(
            ["background-color: #b75d5d", "background-color: #5db75d;"][default]
        )
        self.button.setFixedWidth(
            max(
                self.button.fontMetrics().boundingRect(i).width() + 10
                for i in self.text
            )
        )
        self.button.clicked.connect(self.switch_state)

        layout.addWidget(self.button)

        self.setLayout(layout)

    def switch_state(self):
        """Toggles the state of this button"""
        self.button.setChecked(False)
        if not self.state:
            self.turn_on()  # Turns it on
            self.button.setText(self.text[0])  # Change text and color
            self.button.setStyleSheet("background-color: #5db75d;")
        else:
            self.turn_off()
            self.button.setText(self.text[1])  # Change text and color
            self.button.setStyleSheet("background-color: #b75d5d;")
        self.state = not self.state


class DDSControl(QWidget):
    def __init__(self, manager, ch=0):
        super().__init__()
        self.min = 0.0
        self.max = 400.0
        self.manager = manager
        self.ch = 0

        # Main layout for this widget
        layout = QVBoxLayout()

        topline = QHBoxLayout()
        # Frequency input
        freq_vbox = QVBoxLayout()
        freq_label = QLabel("Frequency (MHz)")
        freq_vbox.addWidget(freq_label)
        self.text = QLineEdit()
        self.text.setText(str(round(self.manager.freqs[ch] / MHz, 3)))
        self.text.setValidator(QDoubleValidator())
        self.text.setAlignment(Qt.AlignCenter)
        freq_vbox.addWidget(self.text)
        topline.addLayout(freq_vbox)
        topline.addStretch()
        # Attenuation input
        att_vbox = QVBoxLayout()
        att_vbox.setAlignment(Qt.AlignBottom)
        att_label = QLabel("Attenuation")

        att_vbox.addWidget(att_label)
        att_vbox.addStretch()
        att_input = QDoubleSpinBox()
        att_input.setRange(0.0, 31.5)
        att_input.setSingleStep(0.5)
        att_input.setDecimals(1)
        att_input.setValue(self.manager.atts[ch])
        att_input.setPrefix("-")
        att_input.setSuffix(" dB")
        att_input.editingFinished.connect(
            lambda: self.manager.set_att((ch, att_input.value()))
        )
        att_vbox.addWidget(att_input)
        topline.addLayout(att_vbox)

        layout.addLayout(topline)

        # Slider and min/max labels
        slider_layout = QHBoxLayout()
        min_label = QLabel(f"{self.min} <b>MHz</b>")
        slider_layout.addWidget(min_label)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setSingleStep(1)
        slider_layout.addWidget(self.slider)

        self.slider.setRange(int(self.min), int(self.max))
        max_label = QLabel(f"{self.max} <b>MHz</b>")
        slider_layout.addWidget(max_label)

        self.slider.setValue(int(self.manager.freqs[ch] / MHz))
        layout.addLayout(slider_layout)

        # connections
        self.text.editingFinished.connect(lambda: self.setfreq(self.text.text()))
        self.slider.valueChanged.connect(lambda x: self.setfreq(x))

        self.setLayout(layout)

    def setfreq(self, val):
        # check its a valid number - if not the text edit went wrong
        try:
            val = float(val)
        except:
            self.text.setText(str(self.slider.value()))
            return

        # guard against recursion
        if val == self.freq or round(float(self.text.text())) == self.slider.value():
            return

        val = min(max(val, self.min), self.max)

        self.manager.set_freq(self.ch, val * MHz)
        self.freq = val

        self.text.setText(str(round(self.freq, 3)))
        self.slider.setValue(int(self.freq))


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
        self.gain.setValidator(QIntValidator(0,3))
        self.gain.editingFinished.connect(lambda: self.manager.set_gain(ch, int(self.gain.text())))
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

        layout.addLayout(bottom)
        self.setLayout(layout)

    def set(self):
        print(
            "Setting",
            self.ch,
            self.sampler.currentIndex(),
            self.P.text(),
            self.I.text(),
            self.Gl.text(),
        )
        self.manager.set_iir(
            self.ch,
            int(self.sampler.currentIndex()),
            float(self.P.text()),
            float(self.I.text()),
            float(self.Gl.text()),
        )


class SingleChannel(QWidget):  # {{{
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

        # Top row: ON/OFF switch, channel name
        # ON/OFF switch {{{
        top = QHBoxLayout()
        self.dds_button = Switch(
            self.manager.en_outs[channel],
            turn_on=lambda: self.manager.enable(channel),
            turn_off=lambda: self.manager.disable(channel),
        )
        top.addWidget(self.dds_button)
        self.pid_button = Switch(
            self.manager.en_outs[channel],
            lambda: self.manager.enable(channel),
            lambda: self.manager.disable(channel),
            "PID",
            "PID",
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
        freq = DDSControl(self.manager, channel)
        tabs.addTab(freq, "DDS")

        # PID
        pid = PIDControl(self.manager, channel)
        tabs.addTab(pid, "PID")

        # GRAPH
        # TODO: Add graphing functionality
        scope = QLabel("")
        tabs.addTab(scope, "Scope")

        vbox.addWidget(tabs)

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox


# }}}


class SUServoGUI(QWidget):  # {{{
    def __init__(self, experiment, core, suservo, suservo_chs):
        super().__init__()
        self.manager = SUServoManager(experiment, core, suservo, suservo_chs)
        self.ch = [SingleChannel(self.manager, i) for i in range(8)]

        self.setWindowTitle("SUServo Manager GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Artiq status {{{
        hbox = QHBoxLayout()
        hbox.addWidget(
            Switch(
                self.manager.enabled,
                self.manager.enable_servo,
                self.manager.disable_servo,
            )
        )
        hbox.addStretch()
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


class SUServoGUIExperiment(EnvExperiment):  # {{{
    """SUServo GUI"""

    def build(self):
        self.setattr_device("scheduler")
        self.core = self.get_device("core")
        self.suservo = self.get_device("suservo")
        self.suservo_chs = [self.get_device(f"suservo_ch{i}") for i in range(8)]

    def run(self):
        self.init_kernel()
        app = QApplication(sys.argv)
        screen = SUServoGUI(self, self.core, self.suservo, self.suservo_chs)
        screen.show()
        app.exec_()

    @kernel
    def init_kernel(self):
        """Initialize core"""
        self.core.reset()


# }}}
