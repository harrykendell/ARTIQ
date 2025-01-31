"""
Simple example of how to retrieve image data from pco.Camera.
"""

from artiq.experiment import *

import time
import numpy as np
import pco

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QDoubleSpinBox
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImage, QPixmap

import pyqtgraph as pg

# logger.addHandler(pco.stream_handler)

triggers = [
    "auto sequence",  # just keeps imaging
    "software trigger",  # waits for a software signal from either a blocking record call or cam.sdk.force_trigger()
    "external exposure start & software trigger",  # takes a picture when Trig goes high
    "external exposure control",  # seems to just always immediately take a picture?
]

BINNING = 1
FULL_ROI = (1, 1, 1392 // BINNING, 1040 // BINNING)
WHOLE_CELL_ROI = (620, 475, 750, 650)
MOT_ROI = (650, 540, 740, 620)
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

    cam.configuration = {
        "timestamp": "binary",
        "trigger": triggers[0],
        "exposure time": 5_00e-6,
        "binning": (BINNING, BINNING),
    }

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
        # actual image
        pg.setConfigOptions(imageAxisOrder="row-major")
        self.layout = QVBoxLayout()
        self.im = pg.ImageView()

        meanplot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        meanplot.setLabel("left", "Mean pixel value")
        meanplot.setLabel("bottom", "Time")
        meanplot.showGrid(x=True, y=True)
        self.means = []
        self.times = []
        self.meancurve = meanplot.plot(
            self.times,
            self.means,
            pen=pg.mkPen("y", width=2),
        )

        self.layout.addWidget(self.im)
        self.layout.addWidget(meanplot)

        self.setLayout(self.layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_image)
        self.timer.start(100)

    def update_image(self):
        # essentially self.cam.wait_for_new_image() but for only fifo mode
        settings = self.cam.rec.get_settings()
        status = self.cam.rec.get_status()

        # sequence mode
        if settings["recorder type"] == 0x0001:
            self.cam.wait_for_new_image()

        # hardware trigger fifo mode
        if settings["recorder type"] == 0x0003:
            if status["dwProcImgCount"] == 0:
                return
        img, meta = self.cam.image(roi=MOT_ROI)
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
        # self.cam.record(10, mode="fifo")


def main_gui():
    app = QApplication([])

    with pco.Camera() as cam:
        init_cam(cam)

        widget = CameraWidget(cam)
        widget.show()

        widget.setWindowTitle(f"{cam.camera_name} ({cam.camera_serial})")
        widget.setGeometry(100, 100, 800, 600)

        app.exec()


if __name__ == "__main__":
    main_gui()
