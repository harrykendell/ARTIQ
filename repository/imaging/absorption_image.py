from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import kernel, rpc
from artiq.language import A, MHz, V, at_mu, delay, ms, now_mu, parallel, s, us
from device_db import server_addr
from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    make_fragment_scan_exp,
)
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera
from repository.imaging.processor import AbsImage  # noqa: E402
from repository.models.devices import SUServoedBeam


class AbsorptionImageExpFrag(ExpFragment):
    """
    Absorption imaging of MOT expansion
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        self.setattr_device("ccb")

        self.setattr_fragment("pco_camera", PcoCamera, num_images=3)
        self.pco_camera: PcoCamera
        self.setattr_param_rebind(
            "exposure_time", self.pco_camera, "exposure_time", default=0.1 * ms
        )
        self.exposure_time: FloatParamHandle

        self.mot: MOT = self.setattr_fragment("MOT", MOT, manual_init=False)

        self.img_beam: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "img_beam", ControlBeamsWithoutCoolingAOM, [SUServoedBeam["IMG"]]
        )

        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=1.0 * ms,
            min=1.0 * us,
            unit="ms",
        )
        self.expansion_time: FloatParamHandle

        self.do_cmot: BoolParamHandle = self.setattr_param(
            "do_cmot", BoolParam, "Do the CMOT step", default=True
        )

        self.do_pgc: BoolParamHandle = self.setattr_param(
            "do_pgc", BoolParam, "Do the PGC step", default=False
        )

        self.atom_number: FloatChannel = self.setattr_result("atom_number")

    @kernel
    def run_once(self):
        self.core.reset()

        self.mot.calculate_dma_handles()
        self.core.break_realtime()

        self.mot.load()
        if self.do_cmot.get():
            self.mot.compress()
            if self.do_pgc.get():
                self.mot.pgc()

        self.mot.drop()
        delay(self.expansion_time.get())

        # image cloud
        with parallel:
            self.img_beam.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME - self.exposure_time.get())

        self.mot.clear_atoms()

        # reference image
        with parallel:
            self.img_beam.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME - self.exposure_time.get())

        # background image
        self.pco_camera.capture_image()
        delay(self.pco_camera.BUSY_TIME)

        # leave the MOT to reload
        self.mot.init()
        self.mot.load(wait_for_load=False)

        self.core.wait_until_mu(now_mu())
        self.update_images()

    @rpc(flags={"async"})
    def update_images(self):
        images = self.pco_camera.retrieve_images(
            roi=self.pco_camera.FULL_ROI, timeout=1 * s
        )
        if images is None:
            raise RuntimeError("Failed to retrieve images from camera")

        for num, img_name in enumerate(["TOF", "REF", "BG"]):
            # save for applet
            self.set_dataset(
                f"Images.absorption.{img_name}", images[num], broadcast=True
            )
        self.set_dataset(
            "Images.absorption.expansion_time",
            self.expansion_time.get(),
            broadcast=True,
        )

        self.absimg = AbsImage(
            data=images[0],
            ref=images[1],
            bg=images[2],
            magnification=0.5,  # Set default magnification
        )

        self.atom_number.push(self.absimg.atom_number)

        # self.ccb.issue(
        #     "create_applet",
        #     "AbsorptionImage",
        #     f"${{python}} -m repository.imaging.applet --server {server_addr}",  # noqa: E501,
        # )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
