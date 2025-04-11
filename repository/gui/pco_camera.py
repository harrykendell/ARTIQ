"""
Simple example of how to retrieve image data from pco.Camera.
"""

# from artiq.experiment import *

import time
import numpy as np
import pco

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QPushButton,
    QHBoxLayout,
    QLabel,
)
from PyQt6.QtCore import QTimer, Qt

from artiq.language.units import ms


import pco.camera_exception
import pco.logging
import pyqtgraph as pg

import sys
sys.path.append(__file__.split("artiq")[0] + "artiq")
from repository.imaging.PCO_Camera import PcoCamera


# logger.addHandler(pco.stream_handler)

triggers = [
    "auto sequence",  # just keeps imaging
    "software trigger",  # waits for a software signal from either a blocking record call or cam.sdk.force_trigger()
    "external exposure start & software trigger",  # takes a picture when Trig goes high
    "external exposure control",  # seems to just always immediately take a picture?
]
"""
For the pixelfly:
    "serial": 19701804,
    "type": "pco.pixelfly usb",

    "min exposure time": 1e-06,
    "max exposure time": 60.0,
    "min exposure step": 1e-06,

    can't do delays
    cant do acquire
    no ram
    no hardware binning
"""


def init_cam(cam: pco.Camera):
    cam.default_configuration()

    pco.logging.logging.getLogger().setLevel(pco.logging.logging.WARNING)

    cam.configuration = {
        "timestamp": "binary",
        "trigger": triggers[0],
        "exposure time": 0.1*ms,
    }
    cam.auto_exposure_off()

    print(f"{cam.camera_name} ({cam.camera_serial})")
    print(cam.configuration)
    print("running in trigger_mode", cam.configuration["trigger"])


class CameraWidget(QWidget):
    def __init__(self, cam: pco.Camera):
        super().__init__()
        self.cam = cam
        self.initUI()

        self.start_recording()

        self.first = True

    def initUI(self):
        # Configure pyqtgraph
        pg.setConfigOptions(imageAxisOrder="row-major")

        # Create a splitter for draggable resizing
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ImageView widget
        self.im = pg.ImageView()
        splitter.addWidget(self.im)

        # PlotWidget for mean pixel values
        self.meanplot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.meanplot.setLabel("left", "Mean pixel value")
        self.meanplot.setLabel("bottom", "Time")
        self.meanplot.showGrid(x=True, y=True)
        self.means = []
        self.times = []
        self.meancurve = self.meanplot.plot(
            self.times,
            self.means,
            pen=pg.mkPen("y", width=2),
        )
        splitter.addWidget(self.meanplot)

        # Set initial sizes for the widgets
        splitter.setSizes([400, 200])  # Initial heights for ImageView and PlotWidget

        # combo box for selecting the ROI
        self.roi_combo = pg.ComboBox()
        self.roi_combo.addItem("MOT", PcoCamera.MOT_ROI)
        self.roi_combo.addItem("Whole Cell", PcoCamera.WHOLE_CELL_ROI)
        self.roi_combo.addItem("Full Image", PcoCamera.FULL_ROI)
        self.roi_combo.setCurrentIndex(2)
        self.roi_combo.currentIndexChanged.connect(self.reset_zoom)
        self.roi_combo.setToolTip("whole cell")
        # prefix the combo box with a label
        self.roi_label = QLabel("ROI:")
        self.roi_label.setBuddy(self.roi_combo)
        self.roi_label.setToolTip("Select the ROI for the image")

        # Button to reset zoom
        self.reset_zoom_button = QPushButton("Reset Zoom")
        self.reset_zoom_button.clicked.connect(self.reset_zoom)
        self.reset_zoom_button.setToolTip("Reset the zoom level of the image")

        # Button to reset data
        self.reset_data_button = QPushButton("Reset Data")
        self.reset_data_button.clicked.connect(self.reset_data)
        self.reset_data_button.setToolTip("Reset the mean pixel values and time")

        # Add the splitter to the layout
        layout = QVBoxLayout()
        layout.addWidget(splitter)

        buttons = QHBoxLayout()
        buttons.addWidget(self.roi_label)
        buttons.addWidget(self.roi_combo)
        buttons.addStretch()
        buttons.addWidget(self.reset_zoom_button)
        buttons.addWidget(self.reset_data_button)

        layout.addLayout(buttons)
        self.setLayout(layout)

        # Timer for updating the image
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_image)
        self.timer.start(80)

    def update_image(self):
        settings = self.cam.rec.get_settings()
        status = self.cam.rec.get_status()

        # Sequence mode
        if settings["recorder type"] == 0x0001:
            self.cam.wait_for_new_image(timeout=1)

        # Hardware trigger FIFO mode
        if settings["recorder type"] == 0x0003:
            if status["dwProcImgCount"] == 0:
                return
        img, meta = self.cam.image(roi=self.roi_combo.currentData())
        self.im.setImage(
            img,
            autoHistogramRange=self.first,
            autoLevels=self.first,
            autoRange=self.first,
        )

        self.times.append(time.time())
        self.means.append(np.mean(img))
        self.meancurve.setData(self.times, self.means)

        self.first = False

    def start_recording(self):
        self.cam.record(10, mode="fifo")

    def reset_zoom(self):
        self.first = True
        self.meanplot.enableAutoRange()

    def reset_data(self):
        # Reset the mean pixel values and time lists
        self.times = []
        self.means = []

    def set_exposure_time(self, time: float):
        """
        Set the exposure time of the camera.
        :param time: Exposure time in seconds.

        must stop recording before setting the exposure time
        """
        if time == self.cam.configuration["exposure time"]*1e6:
            return

        self.spin.clearFocus()
        self.cam.stop()
        self.cam.configuration["exposure time"] = time*1e-6
        self.start_recording()


def main_gui():
    app = QApplication([])
    # don't specify an interface or unclosed cameras cause indefinite hangs
    try:
        with pco.Camera() as cam:
            init_cam(cam)

            widget = CameraWidget(cam)
            widget.show()

            widget.setWindowTitle(f"{cam.camera_name} ({cam.camera_serial})")
            widget.setGeometry(100, 100, 800, 600)

            app.exec()
    except pco.camera_exception.CameraException as e:
        print("If you can't connect... kill any process owning the camera:")
        print("\tkill -9 $(awk '/pco_device/ {print $2}' < <(lsof))")
        print(f"Camera error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main_gui()
