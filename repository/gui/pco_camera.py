"""
Simple example of how to retrieve image data from pco.Camera.
"""

from artiq.experiment import *

import logging
import numpy as np
import pco

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QDoubleSpinBox
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QImage, QPixmap

import pyqtgraph as pg

logger = logging.getLogger()
logger.setLevel(logging.WARNING)
logger.addHandler(pco.stream_handler)

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

    cam.configuration = {
        "timestamp": "binary",
        "trigger": triggers[0],
        "exposure time": 0.1,
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

    def initUI(self):
        # actual image
        pg.setConfigOptions(imageAxisOrder="row-major")
        self.layout = QVBoxLayout()
        self.im = pg.ImageView()
        self.layout.addWidget(self.im)
        self.setLayout(self.layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_image)
        self.timer.start(100)

    def update_image(self):
        self.cam.wait_for_new_image()
        self.im.setImage(self.cam.image()[0])

    def start_recording(self):
        self.cam.record(10, mode="fifo")


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
