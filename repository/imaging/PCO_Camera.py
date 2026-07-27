import logging
import time
from enum import Enum

import numpy as np
import pco
from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import delay, delay_mu, host_only, kernel, rpc
from artiq.language.units import ms, s, us
from ndscan.experiment import (
    EnumParam,
    ExpFragment,
    FloatParam,
    Fragment,
    ParamHandle,
    make_fragment_scan_exp,
)
from ndscan.experiment.parameters import FloatParamHandle

logger = logging.getLogger(__name__)
logging.getLogger("pco").setLevel(logging.WARNING)

dimple_pixel_scan = 10
MOT_SIZE = 300
MOT_X = 680
MOT_Y = 550


def edge_roi_correct(roi):
    """PCO EDGE CAMERA require ROIs to be aligned to 4 pixels, so this function takes an ROI
    FOR MORE DETALIS look at https://www.pco.de/fileadmin/user_upload/downloads/manuals/PCO_Camera_SDK_Manual.pdf"""
    x0, y0, x1, y1 = roi

    # nearest lower valid values
    x0 = 1 + 4 * ((x0 - 1) // 4)
    x1 = 4 * (x1 // 4)

    return (x0, y0, x1, y1)


class ROI(Enum):
    FULL_pixelfly = (1, 1, 1392, 1040)
    MOT_pixelfly = (
        MOT_X - MOT_SIZE,
        MOT_Y - MOT_SIZE,
        MOT_X + MOT_SIZE,
        MOT_Y + MOT_SIZE,
    )
    ODT_Reservoir_pixelfly = (650, 470, 750, 550)
    # ODT_Reservoir_pixelfly = (500, 430, 989, 550)
    # ODT_Reservoir_pixelfly = (400, 300, 989, 700) refrence saved for future use for the moving stage flexiboity in axial direction
    ODT_Dimple_pixelfly = (1, 550 - dimple_pixel_scan, 1260, 650 - dimple_pixel_scan)

    FULL_EDGE = (1, 1, 2000, 2000)
    # MOT_EDGE = edge_roi_correct(MOT_pixelfly)
    # ODT_Reservoir_EDGE = edge_roi_correct((1, 450, 2040, 750))
    # ODT_Dimple_EDGE = edge_roi_correct((
    #     1,
    #     550 - dimple_pixel_scan,
    #     1260,
    #     650 - dimple_pixel_scan,
    # ))


class camera_name(Enum):
    PIXELFLY = "pco.pixelfly usb"
    EDGE = "pco.edge 4.2m LT rolling shutter"


class BUSY_TIME(Enum):
    PCO_edge = 35 * ms
    PCO_pixelfly = 150 * ms


class PcoCamera(Fragment):
    BUSY_TIME = BUSY_TIME

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
            max=5.0 * s,
            unit="ms",
        )
        self.exposure_time: FloatParamHandle

        self.setattr_param(
            "roi",
            EnumParam,
            "Select the region of interest for imaging",
            default=ROI.FULL_pixelfly,
            enum_class=ROI,
        )

        self.setattr_param(
            "camera_used",
            EnumParam,
            "Select which camera to use",
            default=camera_name.PIXELFLY,
            enum_class=camera_name,
        )
        self.camera_used: ParamHandle

        self.setattr_device("pco_camera_pixelfly")
        self.trigger1: TTLInOut = self.pco_camera_pixelfly

        self.setattr_device("pco_camera_edge")
        self.trigger2: TTLInOut = self.pco_camera_edge

        self.debug = logger.getEffectiveLevel() <= logging.WARNING

    def host_setup(self):
        """
        Setup the host-side camera controls
        """
        if self.camera_used.get() == camera_name.EDGE:
            self.cam = pco.Camera(serial=61011464)
            expsoure_time = self.exposure_time.get() + 50 * us
            self.trigger = self.trigger2
            self.trigger_delay = 120 * us
        elif self.camera_used.get() == camera_name.PIXELFLY:
            self.cam = pco.Camera(serial=19701804)
            expsoure_time = self.exposure_time.get()
            self.trigger = self.trigger1
            self.trigger_delay = 6 * us # Empirically determined from max light accumulated
        else:
            raise ValueError(f"Unknown camera selected: {self.camera_used.get()}")
        self.cam.default_configuration()

        self.cam.configuration = {
            "timestamp": "binary",
            "trigger": "external exposure start & software trigger",
            "exposure time": expsoure_time,
        }

        self.cam.auto_exposure_off()
        if self.camera_used.get() == camera_name.EDGE:
            self.cam.sdk.set_roi(*self.roi.get().value)

        logger.warning("ROI requested %s", self.roi.get().value)

        logger.warning("Camera ROI %s", self.cam.sdk.get_roi())

        if self.debug:
            logger.info(f"{self.cam.camera_name} ({self.cam.camera_serial})")
            logger.info(self.cam.configuration)
            logger.info("running in trigger_mode %s", self.cam.configuration["trigger"])
        self.use_edge = self.camera_used.get() == camera_name.EDGE
        super().host_setup()

    @rpc(flags={"async"})
    def set_roi(self, roi: ROI):
        """
        Set the region of interest for imaging, this can be used to speed up retrieval of images by only retrieving a subset of the pixels.
        """
        if self.camera_used.get() == camera_name.EDGE:
            self.cam.sdk.set_roi(*roi.value)
        # for pixelfly cameras we can set the roi when retrieving images, so we don't

    @property
    def camera_busy_time(self):
        if self.camera_used.get() == camera_name.PIXELFLY:
            return self.BUSY_TIME.PCO_pixelfly.value
        elif self.camera_used.get() == camera_name.EDGE:
            return self.BUSY_TIME.PCO_edge.value
        else:
            raise ValueError(f"Unknown camera selected: {self.camera_used.get()}")

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

        We write the trigger into the past by trigger delay so that the camera is triggered at the correct time.

        Another image should not be captured until the previous one has been exposed
        """
        delay(-self.trigger_delay)
        self.trigger.on()
        delay(self.exposure_time.get())
        self.trigger.off()

        delay(-self.exposure_time.get() + self.trigger_delay)

    @host_only
    def retrieve_images(self, timeout=5.0 * s, roi: ROI = ROI.FULL_pixelfly):
        """
        Pulls all stored images off the camera and stores the first
        into the diagnostic dataset
        """

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
        self.images, _ = self.cam.images(roi=roi.value)
        logger.info("Images retrieved")
        self.images = self.rotate_and_flip(self.images).astype(np.float64)

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
            default=0.5 * ms,
        )

        self.setattr_param_rebind(
            "camera_used", self.pco_camera, "camera_used", default=camera_name.PIXELFLY
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


SingleImage = make_fragment_scan_exp(PcoCameraExpFrag)
