"""
Simple example of how to retrieve image data from pco.Camera.
"""

# from artiq.experiment import *

import time
import numpy as np
import pco

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtCore import QTimer

import pco.logging
import pyqtgraph as pg

MOT_SIZE = 40
MOT_X = 715
MOT_Y = 575
MOT_ROI = (MOT_X - MOT_SIZE, MOT_Y - MOT_SIZE, MOT_X + MOT_SIZE, MOT_Y + MOT_SIZE)
WHOLE_CELL_ROI = (3 * 1392 // 8, 3 * 1040 // 8, 5 * 1392 // 8, 5 * 1040 // 8)


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
        "exposure time": 500e-6,
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
        settings = self.cam.rec.get_settings()
        status = self.cam.rec.get_status()

        # sequence mode
        if settings["recorder type"] == 0x0001:
            self.cam.wait_for_new_image()

        # hardware trigger fifo mode
        if settings["recorder type"] == 0x0003:
            if status["dwProcImgCount"] == 0:
                return
        img, meta = self.cam.image(roi=WHOLE_CELL_ROI)
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

    with pco.Camera(interface="USB 2.0") as cam:
        init_cam(cam)

        widget = CameraWidget(cam)
        widget.show()

        widget.setWindowTitle(f"{cam.camera_name} ({cam.camera_serial})")
        widget.setGeometry(100, 100, 800, 600)

        app.exec()


if __name__ == "__main__":
    main_gui()
