##########################################################################################
# Instructions to use:
#       - go to the same directory as the 'device.db' file
#           (otherwise you must specify the correct --device-db)
#       - run this file as `artiq_run dds_control_interface.py`
#      [-] specify `--device-db path/to/device.db` parameter with proper path if needed
#      [-] add a & to the end of the call to run as a background process
##########################################################################################

import sys
from PyQt5.QtWidgets import QWidget, QGroupBox, QVBoxLayout, QPushButton, QDoubleSpinBox, QGridLayout, QApplication, QLabel, QHBoxLayout, QLineEdit, QSlider
from PyQt5.QtCore import Qt
from repository.utils.SUServoManager import SUServoManager

from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel

class OnOff(QWidget):
    def __init__(self, default: bool, turn_on, turn_off):
        super().__init__()
        self.turn_on = turn_on
        self.turn_off = turn_off
        self.state = default

        # Main layout for this widget
        layout = QVBoxLayout()

        self.state_button = QPushButton()
        self.state_button.setText(["OFF","ON"][default])
        self.state_button.setCheckable(True)
        self.state_button.setStyleSheet(["background-color: #b75d5d","background-color: #5db75d;"][default])
        self.state_button.setFixedWidth(self.state_button.fontMetrics().boundingRect("OFF").width()+10)
        self.state_button.clicked.connect(self.switch_state)

        layout.addWidget(self.state_button)

        self.setLayout(layout)

    def switch_state(self):
        """Toggles the state of this button"""
        self.state_button.setChecked(False)
        if not self.state:
            self.turn_on() # Turns it on
            self.state_button.setText("ON") # Change text and color
            self.state_button.setStyleSheet("background-color: #5db75d;")
        else:
            self.turn_off()
            self.state_button.setText("OFF") # Change text and color
            self.state_button.setStyleSheet("background-color: #b75d5d;")
        self.state = not self.state

class TextSliderControl(QWidget):
    def __init__(self, val, unit, set, min=0.0, max=400.0, labels=True):
        super().__init__()
        self.min = min
        self.max = max
        self.set = set
        self.val = val

        # Main layout for this widget
        layout = QVBoxLayout()

        topline = QHBoxLayout()
        # Frequency input
        self.text = QLineEdit()
        self.text.setText(str(self.val))
        topline.addWidget(self.text)

        layout.addLayout(topline)

        # Slider and min/max labels
        slider_layout = QHBoxLayout()
        if labels:
            self.min_label = QLabel(f'{self.min} {unit}')
            self.max_label = QLabel(f'{self.max} {unit}')
            slider_layout.addWidget(self.min_label)
            slider_layout.addWidget(self.max_label)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(int(self.min))
        self.slider.setMaximum(int(self.max))

        # Add widgets to the slider layout
        slider_layout.addWidget(self.slider)

        # Add slider layout to the main layout
        layout.addLayout(slider_layout)

        # Signal connections
        
        self.text.editingFinished.connect(lambda: self.setval(self.text.text()))
        self.slider.valueChanged.connect(self.setval)

        self.setLayout(layout)
        self.setval(self.val)

    def setval(self,val):
        # check its a valid number
        try:
            val = float(val)
        except:
            self.setval(self.val)
            return
        # guard against recursion
        if val == self.val:
            return
        
        val = min(max(val,self.min),self.max)

        self.set(float(val))
        self.val = val

        if str(self.val) != self.text.text():
            self.text.setText(str(self.val))
        if self.slider.value() != int(self.val):
            self.slider.setValue(int(self.val))

class SingleChannel(QWidget): #{{{
    """Class to control a single given SUServo channel"""
    def __init__(self, manager, channel = 0):
        # manager : SUServoManager
        QWidget.__init__(self)
        self.manager = manager
        self.channel = channel

        self.groupbox = QGroupBox()

        # Stack all other widgets vertically
        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # ON/OFF switch {{{
        top = QHBoxLayout()
        self.name = QLabel(f"Channel {channel}")
        top.addWidget(self.name)
        self.state_button = OnOff(self.manager.en_outs[channel], lambda: self.manager.enable(channel), lambda: self.manager.disable(channel))
        top.addWidget(self.state_button)
        vbox.addLayout(top)
        # }}}

        # Frecuency input {{{
        self.freq_input = TextSliderControl(self.manager.freqs[channel]/MHz, "MHz", lambda f: self.manager.set_freq(channel,f),0.,400.,False)
        vbox.addWidget(self.freq_input)
        # }}}

        # Attenuation input {{{
        self.att_input = QDoubleSpinBox()
        self.att_input.setPrefix("Attenuation: ")
        self.att_input.setRange(0., 31.5)
        self.att_input.setValue(self.manager.atts[channel])
        self.att_input.setSuffix(" dB")
        self.att_input.editingFinished.connect(lambda: self.manager.set_att(channel, self.att_input.value()))
        vbox.addWidget(self.att_input)
        # }}}

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox

    # Toggle DDS on/off switch {{{
    def switch_state(self):
        """Toggles the state of this DDS"""
        if self.state_button.isChecked():
            self.manager.enable(self.channel) # Turns it on
            self.state_button.setText("ON") # Change text and color
            self.state_button.setStyleSheet("background-color: #5db75d;")
        else:
            self.manager.disable(self.channel) # Turns it off
            self.state_button.setText("OFF") # Change text and color
            self.state_button.setStyleSheet("background-color: #b75d5d;")
    #}}}

#}}}

class SUServoGUI(QWidget): #{{{
    def __init__(self, experiment, core, suservo, suservo_chs):
        super().__init__()
        self.manager = SUServoManager(experiment, core, suservo, suservo_chs)
        self.ch = [SingleChannel(self.manager, i) for i in range(8)]

        self.setWindowTitle("SUServo Manager GUI")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Artiq status {{{
        hbox = QHBoxLayout()
        self.label = QLabel("SUServo status") # Bold large text
        self.label.setStyleSheet("font: bold 14pt")
        hbox.addWidget(self.label)
        self.power = OnOff(self.manager.enabled, self.manager.enable_servo, self.manager.disable_servo)
        hbox.addWidget(self.power)
        hbox.addStretch()
        layout.addLayout(hbox)
        #}}}

        # Create channels controls
        chans = QGridLayout()
        for i in range(8):
            chans.addWidget(self.ch[i].get_widget(), 0, i)
        layout.addLayout(chans)
#}}}

class SUServoGUIExperiment(EnvExperiment): #{{{
    ''' SUServo GUI'''
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
#}}}
