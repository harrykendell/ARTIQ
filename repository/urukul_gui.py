##########################################################################################
# Instructions to use:
#       - go to the same directory as the 'device.db' file
#           (otherwise you must specify the correct --device-db)
#       - run this file as `artiq_run dds_control_interface.py`
#      [-] specify `--device-db path/to/device.db` parameter with proper path if needed
#      [-] add a & to the end of the call to run as a background process
##########################################################################################

import sys
import os
from PyQt5.QtWidgets import QWidget, QGroupBox, QVBoxLayout, QPushButton, QDoubleSpinBox, QGridLayout, QApplication
# from PyQt5.QtGui import QIcon, QDoubleValidator
# from PyQt5.QtCore import pyqtSlot
import json
from artiq.experiment import *
from artiq.language import ms, MHz, dB, delay

# TODO:
#   [ ] Check why amplitude fails to update
#   [~] Set initial values of inputs to correct ones based on dict
#   [~] └ Look for a saved json at start to get initial values
#   [ ] Check inputs
#   [ ] Add options to specify datafiles
#   [ ] Catch errors and send according popups
#   [ ] Refactor to remove the artiq/dds handle issue
#   [ ] Add tabs to store different configurations

JSON_DATAFILE = 'dds_states.json'

class SingleChannel(QWidget): #{{{
    """Class to control a single given Urukul channel"""
    def __init__(self, core, dds, name="Default Name", initial_pars=None):
        # Must pass artiq and dds handles. I don't know how to work around this
        # but should be doable somehow
        QWidget.__init__(self)

        self.core = core
        self.dds = dds

        if initial_pars is None:
            # PArameter dictionary to store and save current DDS states
            self.state_params = {
                                'state' : 0       ,
                                'freq'  : 200*MHz ,
                                'amp'   : 1.      ,
                                'att'   : 0*dB
                                }
        else:
            self.state_params = initial_pars

        # Each DDS will have each own enablable group
        self.groupbox = QGroupBox(name)
        self.groupbox.setCheckable(True)

        # Stack all other widgets vertically
        vbox = QVBoxLayout()
        self.groupbox.setLayout(vbox)

        # ON/OFF switch {{{
        self.state_button = QPushButton()
        self.state_button.setText("OFF")
        self.state_button.setCheckable(True)
        self.state_button.setDefault(False)
        self.state_button.setStyleSheet("background-color: #b75d5d")
        # Dont't know why I can't pass self.switch_state by itself...
        self.state_button.clicked.connect(lambda: self.switch_state())
        vbox.addWidget(self.state_button)
        # }}}

        # Frecuency input {{{
        self.freq_input = QDoubleSpinBox()
        self.freq_input.setPrefix("Frequency: ")
        self.freq_input.setRange(1., 400., 0.1)
        self.freq_input.setValue(self.state_params['freq'])
        self.freq_input.setSuffix(" MHz")
        self.freq_input.valueChanged.connect(self.freq_change)
        vbox.addWidget(self.freq_input)
        # }}}

        # Amplitude input {{{
        self.amp_input = QDoubleSpinBox()
        self.amp_input.setPrefix("Amplitude: ")
        self.amp_input.setRange(0., 1., 0.1)
        self.amp_input.setValue(self.state_params['att'])
        self.amp_input.valueChanged.connect(self.amp_change)
        vbox.addWidget(self.amp_input)
        # }}}

        # Attenuation input {{{
        self.att_input = QDoubleSpinBox()
        self.att_input.setPrefix("Attenuation: ")
        self.att_input.setRange(0., 31., 0.1)
        self.att_input.setValue(self.state_params['att'])
        self.att_input.setSuffix(" dB")
        self.att_input.valueChanged.connect(self.att_change)
        vbox.addWidget(self.att_input)
        # }}}


    def update_state(self, key, new_state):
        """Update the parameters dictionary"""
        self.state_params[key] = new_state

    def get_state_param(self, key):
        """Get a key from the parameters dictionary"""
        return self.state_params[key]

    def get_state(self):
        """Returns the parameter dictionary"""
        return self.state_params

    def get_widget(self):
        """Return the widgets to the main app"""
        return self.groupbox

    # Toggle DDS on/off switch {{{
    def switch_state(self):
        """Toggles the state of this DDS"""
        if self.state_button.isChecked():
            self.switch_state_kernel(True) # Turns it on
            self.state_button.setText("ON") # Change text and color
            self.state_button.setStyleSheet("background-color: #5db75d;")
        else:
            self.switch_state_kernel(False) # Turns it off
            self.state_button.setText("OFF") # Change text and color
            self.state_button.setStyleSheet("background-color: #b75d5d;")

    @kernel
    def switch_state_kernel(self, state):
        self.core.break_realtime()
        self.dds.sw.set_o(state)

    #}}}

    # Attenuation {{{
    def att_change(self, new_att):
        """Update attenuation on channel"""
        self.att_change_kernel(new_att)
        self.update_state('att', new_att)

    @kernel
    def att_change_kernel(self, new_att):
        self.core.break_realtime()
        self.dds.set_att(new_att)

    # }}}

    # Frequency {{{
    def freq_change(self, new_freq):
        """Update frecuency on channel (Forces MHz)"""
        self.freq_change_kernel(new_freq)
        self.update_state('freq', new_freq*MHz) # Force MHz. Change?

    @kernel
    def freq_change_kernel(self, new_freq):
        self.core.break_realtime()
        delay(10*ms)
        self.dds.set(new_freq*MHz)
    # }}}

    # Amplitude {{{
    def amp_change(self, new_amp):
        """Update amplitude on this channel"""
        self.amp_change_kernel(new_amp)
        self.state_params['amp'] = new_amp

    @kernel
    def amp_change_kernel(self, new_amp):
        self.core.break_realtime()
        # this needs fixing, reading from the dict is not the way
        self.dds.set(self.get_state_param('freq'), amplitude=new_amp)
        self.dds.cpld.io_update.pulse_mu(8) # Try this to get the amplitude updated?
    # }}}
#}}}

class DDSManager(QWidget): #{{{
    """Main application class"""
    def __init__(self, core, ch0, ch1):
        super().__init__()
        #self.artiq = artiq # get the artiq handle
        self.core = core
        self.ch0 = ch0
        self.ch1 = ch1

        # Make a default initial parameter dictionary to pass to the channels
        # in case a real one is found, this gets stepped on with the real values
        initial_params = {'ch0': None, 'ch1': None}
        loaded_params.update(self.load_state())

        self.setWindowTitle("DDS Manager GUI")
        layout = QGridLayout()
        self.setLayout(layout)

        # Create both output widgets
        self.laser_1 = SingleChannel(core, ch0, name="Laser 1",
                                     initial_pars=initial_params['ch0'])
        layout.addWidget(self.laser_1.get_widget(), 0, 0)

        self.laser_2 = SingleChannel(core, ch1, name="Laser 2",
                                     initial_pars=initial_params['ch1'])
        layout.addWidget(self.laser_2.get_widget(), 0, 1)

        save_btn = QPushButton("Save state")
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn, 1, 0)

        start_btn = QPushButton("Start")
        start_btn.clicked.connect(self.start)
        layout.addWidget(start_btn, 1, 1)

    def load_state(self):
        """Load the JSON parameter dictionary if existent"""
        if not os.path.isfile(JSON_DATAFILE):
            return False

        with open(JSON_DATAFILE, "r") as in_json:
            return json.load(in_json)


    def save_state(self):
        """Store the parameter dictionary as a JSON file"""
        ch0_data = self.laser_1.get_state()
        ch1_data = self.laser_2.get_state()
        out_json = {'ch0':ch0_data, 'ch1':ch1_data}
        with open(JSON_DATAFILE, 'w') as log:
            json.dump(out_json, log, indent=1)

    def start(self):
        """TODO: Check scheduler to see if the process be re-started after finished"""
        print(self.artiq.scheduler.get_status())
        self.artiq.scheduler.submit(priority=-1)
        print(self.artiq.scheduler.get_status())
#}}}

class GUIManager(EnvExperiment): #{{{
    def build(self):
        self.core = self.get_device("core")
        self.setattr_device("scheduler")
        self.ch0 = self.get_device("urukul0_ch0")
        self.ch1 = self.get_device("urukul0_ch1")

    def run(self):
        self.init_kernel()
        app = QApplication(sys.argv)
        screen = DDSManager(self.core, self.ch0, self.ch1)
        screen.show()
        sys.exit(app.exec_())

    @kernel
    def init_kernel(self):
        """Initialize core and channels"""
        self.core.reset()
        delay(100*ms)
        self.ch0.cpld.init()
        self.ch0.init()
        self.ch1.cpld.init()
        self.ch1.init()
        self.ch0.sw.off()
        self.ch1.sw.off()
        delay(100*ms)
#}}}
