from time import time

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us

# from repository.models.device_db import server_addr
from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    OpaqueChannel,
    make_fragment_scan_exp,
)


from ndscan.experiment.default_analysis import DefaultAnalysis
from ndscan.experiment.default_analysis import CustomAnalysis
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera
from repository.imaging.processor import AbsImage  # noqa: E402
from repository.models.devices import SUServoedBeam


MAGNIFICATION = 1  # Default magnification for absorption imaging


class TrapFrequencyExpFrag(ExpFragment):
    """
    Trap frequency measurement Release and Recapture method
    1. Load MOT
    2. Compress MOT
    3. PGC
    4. Transfer to ODT
    5. Hold in ODT
    6. Modulate trap position with dipole trap AOMs
    7. Release and image after time of flight
    8. Fit cloud size vs modulation frequency to extract trap frequency
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
            "exposure_time", self.pco_camera, "exposure_time", default=0.11 * ms
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
            "do_cmot", BoolParam, "Do the CMOT step", default=False
        )

        self.do_pgc: BoolParamHandle = self.setattr_param(
            "do_pgc", BoolParam, "Do the PGC step", default=False
        )

        self.odt_hold_time: FloatParamHandle = self.setattr_param(
            "ODT_hold_time",
            FloatParam,
            "Hold time in ODT after CMOT/PGC before imaging",
            default=1.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )
        self.perturbation_pulse_time: FloatParamHandle = self.setattr_param(
            "perturbation_pulse_time",
            FloatParam,
            "Time to apply perturbation to excite COM motion",
            default=1.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )
        
        self.wait_after_perturbation: FloatParamHandle = self.setattr_param(
            "wait_after_perturbation",
            FloatParam,
            "Wait time after perturbation before releasing atoms",
            default=0.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )

        self.atom_number: FloatChannel = self.setattr_result("atom_number")
        self.info: OpaqueChannel = self.setattr_result("info", OpaqueChannel)

    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.device_setup_subfragments()

    @kernel
    def run_once(self):
        self.core.break_realtime()

        self.mot.calculate_dma_handles()
        self.core.break_realtime()
        
        self.mot.odt_reservoir.turn_beams_on()
        self.mot.set_reservoir_trap_power(self.mot.power_reservoir.get())  # set reservoir power to 40mW
        self.mot.load()
        if self.do_cmot.get():
            self.mot.compress(False, True)
            if self.do_pgc.get():
                self.mot.pgc()

        self.mot.drop(False, True)
        delay(self.odt_hold_time.get())
        #perturbation to excite COM motion
        self.mot.odt_reservoir.turn_beams_off()
        delay(self.perturbation_pulse_time.get())
        self.mot.odt_reservoir.turn_beams_on()
        delay(self.wait_after_perturbation.get())
        self.mot.odt_reservoir.turn_beams_off()  # turn off reservoir beam for imaging
        delay(self.expansion_time.get())
        # image cloud
        with parallel:
            self.img_beam.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam.turn_beams_off()
        #self.mot.drop_reservoir()  # turn off reservoir beam for imaging
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
            roi=self.pco_camera.MOT_ROI, timeout=1 * s
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

        self.set_dataset(
            "Images.absorption.timestamp",
            time(),
            broadcast=True,
        )

        self.absimg = AbsImage(
            data=images[0],
            ref=images[1],
            bg=images[2],
            magnification=MAGNIFICATION,  # Set default magnification
        )

        self.atom_number.push(self.absimg.atom_number)
        self.info.push(self.absimg.all_info())

        # self.ccb.issue(
        #     "create_applet",
        #     "AbsorptionImage",
        #     f"${{python}} -m repository.imaging.applet --server {server_addr}",  # noqa: E501,
        # )

class fit():
    pass

TrapFrequency = make_fragment_scan_exp(TrapFrequencyExpFrag)
