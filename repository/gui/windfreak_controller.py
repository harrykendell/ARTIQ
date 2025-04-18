from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QCheckBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from windfreak import SynthHD
from sys import argv

import argparse


class TextSliderControl(QWidget):
    def __init__(self, label, unit, set, get, min=0, max=10000):
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
        self.min_label = QLabel(f"{self.min} {unit}")
        self.max_label = QLabel(f"{self.max} {unit}")
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

    def setval(self, val):
        try:
            val = float(val)
        except ValueError:
            self.setval(self.get())
            return
        if val == self.val:
            return
        self.val = val

        self.set(min(max(val, self.min), self.max))
        new = self.get()
        if str(new) != self.text.text():
            self.text.setText(str(new))
        if self.slider.value() != int(new):
            self.slider.setValue(int(self.get()))


class SynthController(QWidget):
    # we hold state for the synth temperature and each channel's
    # enable and frequency/power
    def __init__(self, port="/dev/ttyACM0"):
        super().__init__()
        self.synth = SynthHD(port)
        self.initUI()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(500)

    def initUI(self):
        self.layout = QVBoxLayout()

        # synth name and temperature - as well as green light if connected
        infobox = QHBoxLayout()
        self.synthname = QLabel(f"{self.synth.model} ({self.synth.serial_number})")
        infobox.addWidget(self.synthname)
        self.temp = QLabel(f"{self.synth.temperature} °C")
        infobox.addStretch()
        infobox.addWidget(self.temp)
        self.layout.addLayout(infobox)

        for ch in range(2):
            topline = QHBoxLayout()

            # Enable checkbox
            enable_checkbox = QCheckBox("")
            self.__dict__[f"ch{ch}_enable"] = enable_checkbox
            enable_checkbox.stateChanged.connect(
                lambda state, ch=ch: setattr(
                    self.synth[ch], "enable", state == Qt.Checked
                )
            )

            # Channel label - in bold
            label = QLabel(f'<b>Channel {["A","B"][ch]}</b>')

            topline.addWidget(enable_checkbox)
            topline.addWidget(label)
            topline.addStretch()
            self.layout.addLayout(topline)

            # Create a horizontal layout for the channel
            channel_layout = QHBoxLayout()

            # Frequency controls
            def set_f(val, channel=self.synth[ch]):
                setattr(channel, "frequency", val * 1e6)

            def get_f(channel=self.synth[ch]):
                return channel.frequency / 1e6

            freq_control = TextSliderControl(
                "Frequency",
                "MHz",
                set_f,
                get_f,
                self.synth[ch].frequency_range["start"] / 1e6,
                self.synth[ch].frequency_range["stop"] / 1e6,
            )
            self.__dict__[f"ch{ch}_freq_control"] = freq_control
            channel_layout.addWidget(freq_control)

            # Power control
            def set_p(val, channel=self.synth[ch]):
                setattr(channel, "power", val)

            def get_p(channel=self.synth[ch]):
                return channel.power

            power_control = TextSliderControl(
                "Power",
                "dBm",
                set_p,
                get_p,
                self.synth[ch].power_range["start"],
                self.synth[ch].power_range["stop"],
            )
            self.__dict__[f"ch{ch}_power_control"] = power_control
            channel_layout.addWidget(power_control)

            # Add the channel layout to the main layout
            self.layout.addLayout(channel_layout)

        self.setLayout(self.layout)
        self.setWindowTitle("Windfreak Controller")

        self.update()

    def update(self):
        self.synth.save()
        self.temp.setText(f"{self.synth.temperature} °C")
        # get enable/frequency/power for each channel and update the UI
        for ch in range(2):
            channel = self.synth[ch]
            self.__dict__[f"ch{ch}_enable"].setChecked(channel.enable)
            if self.__dict__[f"ch{ch}_freq_control"].val != channel.frequency / 1e6:
                self.__dict__[f"ch{ch}_freq_control"].text.setText(
                    str(channel.frequency / 1e6)
                )
            if self.__dict__[f"ch{ch}_power_control"].val != channel.power:
                self.__dict__[f"ch{ch}_power_control"].text.setText(str(channel.power))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Controller for the Windfreak RF device",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=str,
        help="The port to open the Windfreak device on",
        default="/dev/ttyACM0",
    )
    args = parser.parse_args()

    app = QApplication(argv)
    # Set a nice icon
    app.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/do.png"))
    app.setStyle("Fusion")
    app.setApplicationName("Windfreak Controller")

    try:
        controller = SynthController(args.port)
    except Exception as e:
        print(f"Failed to open Windfreak device: {e}")
        print(
            "Permission denied errors "
            "-> try running with sudo or adding user to dialout group"
        )
        print(
            "Port not found errors"
            "-> check the port is correct and that the device is connected"
        )
        print(
            "Formatting/terminator value errors"
            "-> check the port isn't a different device"
        )
        exit(1)
    controller.show()

    app.exec_()
