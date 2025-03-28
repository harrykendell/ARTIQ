import logging
import pco
import time
import numpy as np

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import kernel, rpc, host_only, delay, delay_mu
from artiq.language.units import ms, s, us
from ndscan.experiment import (
    Fragment,
    ExpFragment,
    FloatParam,
    IntParam,
    make_fragment_scan_exp,
)
from device_db import server_addr

from ndscan.experiment.parameters import FloatParamHandle, IntParamHandle

logger = logging.getLogger(__name__)
logging.getLogger("pco").setLevel(logging.WARNING)


class PcoCamera(Fragment):
    FULL_ROI = (1, 1, 1392, 1040)
    WHOLE_CELL_ROI = (3 * 1392 // 8, 3 * 1040 // 8, 5 * 1392 // 8, 5 * 1040 // 8)
    MOT_SIZE = 40; MOT_X = 715; MOT_Y = 575 # noqa
    MOT_ROI = (MOT_X - MOT_SIZE, MOT_Y - MOT_SIZE, MOT_X + MOT_SIZE, MOT_Y + MOT_SIZE)

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_param(
            "num_images",
            IntParam,
            "The number of images we will take",
            default=4,
            min=0,
            max=10,
        )
        self.num_images: IntParamHandle

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
        self.pco_camera: TTLInOut

        self.debug = logger.getEffectiveLevel() <= logging.INFO

    def host_setup(self):
        """
        Setup the host-side camera controls
        """

        self.cam = pco.Camera(interface="USB 2.0")
        self.cam.default_configuration()

        self.cam.configuration = {
            "timestamp": "binary",
            "trigger": "external exposure start & software trigger",
            "exposure time": self.exposure_time.get(),
        }

        self.cam.stop()

        if self.debug:
            logger.info(f"{self.cam.camera_name} ({self.cam.camera_serial})")
            logger.info(self.cam.configuration)
            logger.info("running in trigger_mode %s", self.cam.configuration["trigger"])
        self.cam.record(self.num_images.get(), mode="sequence non blocking")

        if self.debug:
            logger.info(f"Recording {self.num_images.get()} images")

        super().host_setup()

    def host_cleanup(self):
        self.cam.close()
        if self.debug:
            logger.info("PCO Camera closed")
        super().host_cleanup()

    @rpc(flags={"async"})
    def set_exposure_time(self, exposure_time: float):
        """
        Set the exposure time of the camera

        temporarily stops recording to make the change
        """
        self.cam.stop()
        self.cam.configuration = {"exposure time": exposure_time}
        self.cam.record(self.num_images.get(), mode="sequence non blocking")

    @kernel
    def device_setup(self):
        """
        Initialise the camera ready to be triggered
        """
        self.core.break_realtime()

        self.pco_camera.output()
        delay_mu(10)
        self.pco_camera.off()

        if self.debug:
            logger.info("PCO Camera setup")

    @kernel
    def capture_image(self) -> None:
        """
        Capture an image, this doesn't advance the timeline.

        Another image should not be captured until the previous one has been exposed
        """
        self.pco_camera.on()
        delay(1 * us)
        self.pco_camera.off()

    @host_only
    def retrieve_images(self, timeout=5.0 * s, roi=WHOLE_CELL_ROI):
        """
        Pulls all stored images off the camera and stores the first into the diagnostic dataset
        """

        # spin for 5 secs hoping we get all the images we were promised
        now = time.time()
        while time.time() - now < timeout:
            logger.info(
                "Waiting for images %s / %s for %.1f / %.1f",
                self.cam.recorded_image_count,
                self.num_images.get(),
                time.time() - now,
                timeout,
            )
            if self.cam.recorded_image_count == self.num_images.get():
                break
            time.sleep(timeout / 10)
        else:
            logging.warning(
                "Recieved %d images, expected %d",
                self.cam.recorded_image_count,
                self.num_images.get(),
            )
            if self.cam.recorded_image_count == 0:
                return None

        self.images, _ = self.cam.images(roi=roi)
        self.images = self.rotate_and_flip(self.images).astype(np.float64)
        self.set_dataset(
            "Images.Latest_image", self.images[-1], broadcast=True, persist=True
        )

        if self.debug:
            logger.info("Images retrieved")

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

        self.setattr_fragment("pco_camera", PcoCamera)
        self.pco_camera: PcoCamera

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
