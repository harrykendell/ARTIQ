"""
Simple example of how to retrieve image data from pco.Camera.
"""

from artiq.experiment import *
import time
import logging
import pco
import pco.sdk

logger = logging.getLogger()
logger.setLevel(logging.WARNING)
logger.addHandler(pco.stream_handler)

triggers = [
    "auto sequence",  # just keeps imaging
    "software trigger",  # waits for a software signal from either a blocking record call or cam.sdk.force_trigger()
    "external exposure start & software trigger",  # takes a picture when Trig goes high
    "external exposure control", # seems to just always immediately take a picture?
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


def main():
    with pco.Camera() as cam:

        cam.default_configuration()
        cam.configuration = {
            "timestamp": "binary",
            "trigger": triggers[3],
        }
        print(f"{cam.camera_name} ({cam.camera_serial})")
        print(cam.configuration)
        print("running in trigger_mode", cam.configuration["trigger"])

        cam.record(1,mode="sequence non blocking")
        while cam.is_recording:
            time.sleep(.1)
            # print("triggering...")
            # cam.sdk.force_trigger()

        print(cam.images())

        print("done")


if __name__ == "__main__":
    main()
