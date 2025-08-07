import logging
import time

import numpy as np
import pco

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import delay, delay_mu, host_only, kernel, rpc
from artiq.language.units import ms, s, us
from repository.models.device_db import server_addr
from ndscan.experiment import (
    ExpFragment,
    FloatParam,
    Fragment,
    make_fragment_scan_exp,
)
from ndscan.experiment.parameters import FloatParamHandle

logger = logging.getLogger(__name__)
logging.getLogger("pco").setLevel(logging.WARNING)


class PcoCamera(Fragment):
    FULL_ROI = (1, 1, 1392, 1040)
    MOT_SIZE = 300
    MOT_X = 770

    MOT_Y = 600

    MOT_ROI = (MOT_X - MOT_SIZE, MOT_Y - MOT_SIZE, MOT_X + MOT_SIZE, MOT_Y + MOT_SIZE)
    WHOLE_CELL_ROI = (
        MOT_X - 100,
        MOT_Y - 150,
        MOT_X + 100,
        MOT_Y + 150,
    )
    BUSY_TIME = 150 * ms

    def build_fragment(self, num_images=1):
        self.num_images = num_images

        self.setattr_device("core")
        self.core: Core

        self.setattr_param(
            "exposure_time",
            FloatParam,
            "The exposure time of the camera",
            default=0.5 * ms,
            min=1.0 * us,
            max=60.0 * s,
            unit="ms",
        )
        self.exposure_time: FloatParamHandle

        self.setattr_device("pco_camera")
        self.trigger: TTLInOut = self.pco_camera

        self.debug = logger.getEffectiveLevel() <= logging.INFO
        self.counter = 0

    def host_setup(self):
        """
        Setup the host-side camera controls
        """
        # don't specify an interface or unclosed cameras cause indefinite hangs
        self.cam = pco.Camera()
        self.cam.default_configuration()

        self.cam.configuration = {
            "timestamp": "binary",
            "trigger": "external exposure start & software trigger",
            "exposure time": self.exposure_time.get(),
        }
        self.cam.auto_exposure_off()

        if self.debug:
            logger.info(f"{self.cam.camera_name} ({self.cam.camera_serial})")
            logger.info(self.cam.configuration)
            logger.info("running in trigger_mode %s", self.cam.configuration["trigger"])

        super().host_setup()

    def host_cleanup(self):
        if hasattr(self, "cam"):
            self.cam.close()
            if self.debug:
                logger.info("PCO Camera closed")
        else:
            logger.warning("PCO Camera was not opened, cannot close it")
        super().host_cleanup()

    @rpc(flags={"async"})
    def set_exposure_time(self, exposure_time: float):
        """
        Set the exposure time of the camera

        temporarily stops recording to make the change
        """
        self.cam.stop()
        self.cam.configuration = {"exposure time": exposure_time}
        self.cam.record(self.num_images, mode="sequence non blocking")

    @kernel
    def device_setup(self):
        """
        Initialise the camera ready to be triggered
        """
        self.core.break_realtime()
        self.trigger.output()
        delay_mu(10)
        self.trigger.off()
        self.cam.stop()
        self.cam.record(self.num_images, mode="sequence non blocking")

        if self.debug:
            logger.info("Recording %s images", self.num_images)

    @kernel
    def capture_image(self) -> None:
        """
        Capture an image, this doesn't advance the timeline.

        Another image should not be captured until the previous one has been exposed
        """
        self.trigger.on()
        delay(1 * us)
        self.trigger.off()

    @host_only
    def retrieve_images(self, timeout=5.0 * s, roi=WHOLE_CELL_ROI):
        """
        Pulls all stored images off the camera and stores the first
        into the diagnostic dataset
        """

        # spin hoping we get all the images we were promised
        now = time.time()
        while time.time() - now < timeout:
            logger.info(
                "Waiting for images %s / %s for %.1f / %.1f",
                self.cam.recorded_image_count,
                self.num_images,
                time.time() - now,
                timeout,
            )
            if self.cam.recorded_image_count == self.num_images:
                break
            time.sleep(timeout / 10)
        else:
            return None
        logger.info("All images counted")
        self.images, _ = self.cam.images(roi=roi)
        logger.info("Images retrieved")
        self.images = self.rotate_and_flip(self.images).astype(np.float64)
        self.set_dataset("Images.Latest_image", self.images[-1], broadcast=True)

        for img in self.images:
            self.set_dataset(
                f"Images.All.{self.counter}",
                img,
                broadcast=False,
            )
            self.counter += 1
        return self.images

    @host_only
    def rotate_and_flip(self, images):
        return np.rot90(np.flip(images, 2), axes=(1, 2))


class PcoCameraExpFrag(ExpFragment):
    """
    Take a single image with the PCO camera
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")

        logging.debug("Setting up PCO camera fragment")
        self.setattr_fragment("pco_camera", PcoCamera, num_images=1)
        self.pco_camera: PcoCamera

        self.setattr_param_rebind(
            "exposure_time",
            self.pco_camera,
            "exposure_time",
            default=5 * ms,
        )

        logging.debug("PCO camera fragment setup complete")

    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.device_setup_subfragments()

    @kernel
    def run_once(self):
        self.core.break_realtime()

        self.pco_camera.capture_image()

        self.update_image()

    @rpc(flags={"async"})
    def update_image(self):
        _ = self.pco_camera.retrieve_images()

        self.ccb.issue(
            "create_applet",
            "Latest Image",
            f"${{artiq_applet}}image Images.Latest_image --server {server_addr}",
        )


SingleImage = make_fragment_scan_exp(PcoCameraExpFrag)
