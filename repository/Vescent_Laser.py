# from windfreak import SynthHD
# kHz = 1e3; MHz = 1e6; GHz = 1e9

# def print_channel(channel):
#     print("    Channel %s" % channel._index, "(enabled)" if channel.enable else "(disabled)")
#     print("        Power: %.2f dBm" % channel.power," - " , channel.power_range)
#     print("        Frequency: %.2f Hz" % channel.frequency," - " , channel.frequency_range)

# synth = SynthHD('/dev/ttyACM0')

# # Set channel 0 power and frequency
# synth[0].power = -10.
# synth[0].frequency = 77.04*MHz
# synth[0].enable = True

# synth[1].power = -10.
# synth[1].frequency = 2930*MHz
# synth[1].enable = True

# synth.save()

# print(synth.model, "(" , synth.serial_number, ") on ", synth.firmware_version)
# print(synth.temperature, "°C")
# for channel in synth:
#     print_channel(channel)

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QCheckBox
from PyQt5.QtCore import Qt,QTimer
from windfreak import SynthHD

class TextSliderControl(QWidget):
    def __init__(self, label, unit, set,get, min=0, max=10000):
        super().__init__()
        self.min = min
        self.max = max
        self.set = set
        self.get = get
        self.val = None

        # Main layout for this widget
        layout = QVBoxLayout()

        topline = QHBoxLayout()
        # Frequency input
        self.text = QLineEdit()
        topline.addWidget(self.text)

        # Label for the control
        self.label = QLabel(label)
        topline.addWidget(self.label)

        layout.addLayout(topline)

        # Slider and min/max labels
        slider_layout = QHBoxLayout()
        self.min_label = QLabel(f'{self.min} {unit}')
        self.max_label = QLabel(f'{self.max} {unit}')
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(int(self.min))
        self.slider.setMaximum(int(self.max))

        # Add widgets to the slider layout
        slider_layout.addWidget(self.min_label)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(self.max_label)

        # Add slider layout to the main layout
        layout.addLayout(slider_layout)

        # Signal connections
        
        self.text.editingFinished.connect(lambda: self.setval(self.text.text()))
        self.slider.valueChanged.connect(self.setval)

        self.setLayout(layout)
        self.setval(self.get())

    def setval(self,val):
        try:
            val = float(val)
        except:
            self.setval(self.get())
            return
        if val == self.val:
            return
        self.val = val

        self.set(min(max(val,self.min),self.max))
        new = self.get()
        if str(new) != self.text.text():
            self.text.setText(str(new))
        if self.slider.value() != int(new):
            self.slider.setValue(int(self.get()))


class SynthController(QWidget):
    # we hold state for the synth temperature and each channel's enable and frequency/power
    def __init__(self):
        super().__init__()
        self.synth = SynthHD('/dev/ttyACM0')
        self.initUI()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(500)

    def initUI(self):
        self.layout = QVBoxLayout()

        # synth name and temperature - as well as green light if connected
        infobox = QHBoxLayout()
        self.synthname = QLabel(f'{self.synth.model} ({self.synth.serial_number})')
        infobox.addWidget(self.synthname)
        self.temp = QLabel(f'{self.synth.temperature} °C')
        infobox.addStretch()
        infobox.addWidget(self.temp)
        self.layout.addLayout(infobox)

        for ch in range(2):
            topline = QHBoxLayout()

            # Enable checkbox
            enable_checkbox = QCheckBox('')
            self.__dict__[f'ch{ch}_enable'] = enable_checkbox
            enable_checkbox.stateChanged.connect(lambda state, ch=ch: setattr(self.synth[ch], 'enable', state==Qt.Checked))

            # Channel label - in bold
            label = QLabel(f'<b>Channel {ch}</b>')

            topline.addWidget(enable_checkbox)
            topline.addWidget(label)
            topline.addStretch()
            self.layout.addLayout(topline)

            # Create a horizontal layout for the channel
            channel_layout = QHBoxLayout()

            # Frequency controls
            set_f = lambda val, channel=self.synth[ch]: setattr(channel, 'frequency', val*1e6)
            get_f = lambda channel=self.synth[ch]: channel.frequency/1e6
        
            freq_control = TextSliderControl('Frequency', 'MHz',set_f,get_f,self.synth[ch].frequency_range['start']/1e6, self.synth[ch].frequency_range['stop']/1e6)
            self.__dict__[f'ch{ch}_freq_control'] = freq_control
            channel_layout.addWidget(freq_control)

            # Power control
            set_p = lambda val, channel=self.synth[ch]: setattr(channel, 'power', val)
            get_p = lambda channel=self.synth[ch]: channel.power
            power_control = TextSliderControl('Power', 'dBm', set_p,get_p, self.synth[ch].power_range['start'], self.synth[ch].power_range['stop'])
            self.__dict__[f'ch{ch}_power_control'] = power_control
            channel_layout.addWidget(power_control)

            # Add the channel layout to the main layout
            self.layout.addLayout(channel_layout)

        self.setLayout(self.layout)
        self.setWindowTitle('Synth Controller')

        self.update()

    def update(self):
        self.synth.save()
        self.temp.setText(f'{self.synth.temperature} °C')
        # get enable/frequency/power for each channel and update the UI
        for ch in range(2):
            channel = self.synth[ch]
            self.__dict__[f'ch{ch}_enable'].setChecked(channel.enable)
            if self.__dict__[f'ch{ch}_freq_control'].val != channel.frequency/1e6:
                self.__dict__[f'ch{ch}_freq_control'].text.setText(str(channel.frequency/1e6))
            if self.__dict__[f'ch{ch}_power_control'].val != channel.power:
                self.__dict__[f'ch{ch}_power_control'].text.setText(str(channel.power))

if __name__ == '__main__':
    app = QApplication([])
    controller = SynthController()
    controller.show()

    app.exec_()