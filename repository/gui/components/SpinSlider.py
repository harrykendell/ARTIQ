# A PyQt Widget that combines a SpinBox and a Slider
#
#   - ScientificSpinBox
#   - Synchronized slider and spinbox
#   - Signal emmited when the value changes
#   - Units for the minimum and maximum labels

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal as Signal
from ScientificSpin import ScientificSpin
from artiq.gui.tools import disable_scroll_wheel

import logging
from math import floor, ceil, pi

logger = logging.getLogger(__name__)


# only inherit from QWidget as we need to keep state synced
class SpinAndSlider(QWidget):
    valueChanged = Signal(float)

    def __init__(
        self, parent=None, min=0.0, max=100.0, unit="", initialValue=None, label=""
    ):
        super().__init__(parent)
        # ensure min < max
        self.min, self.max = (min, max) if min < max else (max, min)
        self.num_decimals = 2

        self.label = label
        self.unit = unit

        self.current_value = min if initialValue is None else initialValue

        self.initUI()
        self.setStep(1)

    def initUI(self):
        layout = QVBoxLayout()

        self.title = QLabel(f"<b>{self.label}<b>")

        self.spin = ScientificSpin()
        disable_scroll_wheel(self.spin)
        self.spin.setDecimals(3)
        # disable arrow buttons and stepBy
        self.spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.spin.stepBy = lambda x: None

        self.spin.setMinimum(self.min)
        self.spin.setMaximum(self.max)
        self.spin.setValue(self.current_value)
        # self.spin.valueChanged.connect(self.spinChanged)
        # only update when the user has finished editing
        self.spin.editingFinished.connect(lambda: self.spinChanged(self.spin.value()))

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(floor(self.min * 10**self.num_decimals))
        self.slider.setMaximum(ceil(self.max * 10**self.num_decimals))
        self.slider.setValue(int(self.current_value * 10**self.num_decimals))
        self.slider.valueChanged.connect(self.sliderChanged)

        self.min_label = QLabel(
            f"{self.spin.textFromValue(self.min)} <b>{self.unit}</b>"
        )
        self.max_label = QLabel(
            f"{self.spin.textFromValue(self.max)} <b>{self.unit}</b>"
        )

        vbox = QVBoxLayout()
        layout.addLayout(vbox)

        topbox = QHBoxLayout()
        topbox.addWidget(self.title)
        # topbox.addStretch()
        topbox.addWidget(self.spin)
        vbox.addLayout(topbox)

        bottombox = QHBoxLayout()
        bottombox.addWidget(self.min_label)
        bottombox.addWidget(self.slider)
        bottombox.addWidget(self.max_label)
        vbox.addLayout(bottombox)

        self.setLayout(layout)

    def spinChanged(self, value):
        if value == self.current_value:
            logger.debug("Spin value unchanged")
            return
        logger.debug("Spin changed to %s", value)
        self.current_value = value
        self.slider.setValue(int(value * 10**self.num_decimals))
        self.valueChanged.emit(value)
        self.spin.clearFocus()

    def sliderChanged(self, value):
        value = value / 10**self.num_decimals
        if value == self.current_value:
            logger.debug("Slider value unchanged")
            return
        logger.debug("Slider changed to %s", value)

        # NB we could be out of range as the slider is integer only
        if value < self.min:
            value = self.min
            logger.debug("Clamping to min")
        elif value > self.max:
            value = self.max
            logger.debug("Clamping to max")

        self.current_value = value
        self.spin.setValue(float(value))

        # remove focus
        self.slider.setFocus()

        self.valueChanged.emit(value)

    def setUnit(self, unit=""):
        self.unit = unit
        self.min_label.setText(
            f"{self.spin.textFromValue(self.min)} <b>{self.unit}</b>"
        )
        self.max_label.setText(
            f"{self.spin.textFromValue(self.max)} <b>{self.unit}</b>"
        )

    def setValue(self, value):
        self.current_value = value
        self.spin.setValue(value)
        self.slider.setValue(int(value * 10**self.num_decimals))

    def setRange(self, min, max):
        self.min, self.max = (min, max) if min < max else (max, min)

        self.spin.setMinimum(min)
        self.spin.setMaximum(max)
        self.slider.setMinimum(min * 10**self.num_decimals)
        self.slider.setMaximum(max * 10**self.num_decimals)

        self.min_label.setText(
            f"{self.spin.textFromValue(self.min)} <b>{self.unit}</b>"
        )
        self.max_label.setText(
            f"{self.spin.textFromValue(self.max)} <b>{self.unit}</b>"
        )

        # clamp the current value to the new range
        self.setValue(min(max(self.current_value, min), max))

    def setLabel(self, label):
        self.title.setText(label)

    def setDecimals(self, decimals):
        self.num_decimals = decimals
        self.spin.setDecimals(decimals)

        # update the slider range
        self.slider.setMinimum(self.min * 10**decimals)
        self.slider.setMaximum(self.max * 10**decimals)
        self.slider.setValue(int(self.current_value * 10**decimals))

    def setStep(self, step):
        self.spin.setSingleStep(step)
        self.slider.setSingleStep(step)

    def setSuffix(self, suffix):
        self.spin.setSuffix(suffix)

    def setEnabled(self, value):
        self.spin.setEnabled(value)
        self.slider.setEnabled(value)

    def value(self):
        return self.current_value

    def minimum(self):
        return self.min

    def maximum(self):
        return self.max

    def setMinimum(self, min):
        self.setRange(min, self.max)

    def setMaximum(self, max):
        self.setRange(self.min, max)


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    logger.setLevel(logging.DEBUG)

    app = QApplication(sys.argv)
    ex = SpinAndSlider(min=0, max=1000, initialValue=pi, label="Frequency", unit="MHz")
    ex.show()

    ex.valueChanged.connect(lambda x: print("Value changed to", x))
    sys.exit(app.exec_())
