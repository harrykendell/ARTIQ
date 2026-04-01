from collections.abc import Iterable
from time import time
 
from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us
import numpy as np
from scipy.optimize import curve_fit
from matplotlib import pyplot as plt
 
# from repository.models.device_db import server_addr
from ndscan.experiment import (
    BoolParam,
    EnumParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    OpaqueChannel,
    make_fragment_scan_exp,
)
 
from artiq.coredevice.ttl import TTLInOut
from ndscan.experiment.default_analysis import DefaultAnalysis, OnlineFit, CustomAnalysis
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera, ROI
from repository.imaging.processor import AbsImage, AbsImageSettings  # noqa: E402
from repository.models.devices import SUServoedBeam
# from repository.Dipole_trap.moving_stage import MovingStage
 
 
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
            "exposure_time", self.pco_camera, "exposure_time", default=0.11 * ms
        )
        self.exposure_time: FloatParamHandle
 
        self.mot: MOT = self.setattr_fragment("MOT", MOT, manual_init=False)
 
        self.img_beam: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "img_beam", ControlBeamsWithoutCoolingAOM, [SUServoedBeam["IMG"]]
        )
 
        self.setattr_device("moving_stage_ttl")
        self.moving_stage_trigger: TTLInOut = self.moving_stage_ttl
 
        # self.setattr_fragment("absolute_moving_stage", MovingStage)
        # self.absolute_moving_stage: MovingStage
 
        # self.setattr_param_rebind(
        #    "moving_absolute_distance",
        #   self.absolute_moving_stage,
        #    "moving_absolute_distance",
        #   default=1.0,
        # )
        self.moving_absolute_distance: FloatParamHandle
 
        self.setattr_param(
            "magnification",
            FloatParam,
            "Magnification for imaging",
            default=1.0,
        )
        self.magnification: FloatParamHandle
 
        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=0.5 * ms,
            min=1.0 * us,
            unit="ms",
        )
        self.expansion_time: FloatParamHandle
 
        # enum selection of ROI for retrieving images
        self.setattr_param(
            "imaging_roi",
            EnumParam,
            "Select imaging ROI",
            default=ROI.FULL,
            enum_class=ROI,
        )
        self.imaging_roi: ParamHandle
 
        self.do_cmot: BoolParamHandle = self.setattr_param(
            "do_cmot", BoolParam, "Do the CMOT step", default=False
        )
 
        self.do_pgc: BoolParamHandle = self.setattr_param(
            "do_pgc", BoolParam, "Do the PGC step", default=False
        )
 
        self.trap_frequency_odt: BoolParamHandle = self.setattr_param(
            "trap_frequency", BoolParam, "Do the trap frequency step", default=False
        )
 
        self.odt_active: BoolParamHandle = self.setattr_param(
            "ODT_active",
            BoolParam,
            "ODT beams active",
            default=False,
        )
 
        self.do_evaporation1: BoolParamHandle = self.setattr_param(
            "do_evaporation1",
            BoolParam,
            "Do the evaporation step 1",
            default=False,
        )
        self.do_evaporation2: BoolParamHandle = self.setattr_param(
            "do_evaporation2",
            BoolParam,
            "Do the evaporation step 2",
            default=False,
        )
        self.odt_hold_time: FloatParamHandle = self.setattr_param(
            "ODT_hold_time",
            FloatParam,
            "Hold time in ODT after CMOT/PGC before imaging",
            default=50.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )
        self.release_time: FloatParamHandle = self.setattr_param(
            "release_time",
            FloatParam,
            "Time to release the atoms",
            default=1.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )
        self.hold_timeafter_release: FloatParamHandle = self.setattr_param(
            "hold_timeafter_release",
            FloatParam,
            "Hold time after releasing the atoms",
            default=1.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )
 
        self.atom_number: FloatChannel = self.setattr_result("atom_number")
        self.sigmax_mm: FloatChannel = self.setattr_result("sigmax_mm")
        self.sigmay_mm: FloatChannel = self.setattr_result("sigmay_mm")
        self.phase_space_density: FloatChannel = self.setattr_result("phase_space_density")
        self.info: OpaqueChannel = self.setattr_result("info", OpaqueChannel)
        self.gaussian_fit_centre_x: FloatChannel = self.setattr_result("gaussian_fit_centre_x")
        self.gaussian_fit_centre_y: FloatChannel = self.setattr_result("gaussian_fit_centre_y")
 
    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.device_setup_subfragments()
 
    @kernel
    def run_once(self):
        self.core.break_realtime()
        self.mot.calculate_dma_handles()
        self.core.break_realtime()
    
        # if (
        #   self.odt_active.get()
        #   or self.do_evaporation1.get()
        #   or self.do_evaporation2.get()
        # ):
        self.mot.set_dimple_trap_power(self.mot.power_dimple.get())
        # self.mot.set_reservoir_trap_power(self.mot.power_reservoir.get())
 
        # self.mot.odt_reservoir.turn_beams_on()
        # self.mot.odt_dimple.turn_beams_on()
        # self.mot.cpt_shutter.off()
        # self.absolute_moving_stage.set_stage_absolute(10.00, 0)
        # self.absolute_moving_stage.move_stage_absolute()
 
        # delay(1 * s)
        # move stage to imaging position
        # self.moving_stage_trigger.pulse(10 * ms)  # trigger moving stage
 
        self.mot.load()
        if self.do_cmot.get():
            # self.kdc101()
            self.mot.compress(
                evaporation_active=self.do_evaporation1.get()
                or self.do_evaporation2.get(),
                odt_active=self.odt_active.get(),
            )
            if self.do_pgc.get():
                self.mot.pgc()
 
        # dropping and locking mot again to resonance for imaging
        self.mot.drop(
            evaporation_active=self.do_evaporation1.get() or self.do_evaporation2.get(),
            odt_active=self.odt_active.get(),
            cmot_active=self.do_cmot.get(),
            pgc_active=self.do_pgc.get(),
        )
 
        # if odt is active turn on odt beams
        if self.odt_active.get():
            delay(self.odt_hold_time.get())  # hold time in odt before imaging
            if not self.do_evaporation1.get() or self.do_evaporation2.get():
                self.mot.drop_dimple()  # turn off dimple beam for imaging
                self.mot.drop_reservoir()  # turn off reservoir beam for imaging
 
        if self.trap_frequency_odt.get():
            delay(self.release_time.get())
            self.mot.on_reservoir()  # turn off reservoir beam for imaging
            delay(self.hold_timeafter_release.get())
            self.mot.drop_reservoir()  # turn off reservoir beam for imaging
 
        # Evaporation and then switch off odt beams
        if self.do_evaporation1.get():
            self.mot.evaporation1(
                single_step_evaporation=not self.do_evaporation2.get()
            )
            if self.do_evaporation2.get():
                self.mot.evaporation2()
 
        # SHUTTER FOR THE cpt
        # self.mot.cpt_shutter.on()
        # delay(35 * ms)  # wait for the shutter to open properly
 
        delay(self.expansion_time.get())
        # self.moving_stage_trigger.on()
        # delay(10 * us)  # wait for the stage to move
        # self.moving_stage_trigger.off()
        # self.mot.cpt_shutter.off()
 
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
            roi=self.imaging_roi.get(), timeout=1 * s
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
 
        settings = AbsImageSettings(
            magnification=self.magnification.get()
        )  # Set default magnification
 
        self.set_dataset(
            "Images.absorption.settings",
            settings.to_dataset(),
            broadcast=True,
        )
 
        self.absimg = AbsImage(
            data=images[0],
            ref=images[1],
            bg=images[2],
            settings=settings,
        )
 
        self.atom_number.push(self.absimg.atom_number)
        self.info.push(self.absimg.all_info())
        self.sigmax_mm.push(self.absimg.sigmax)
        self.sigmay_mm.push(self.absimg.sigmay)
        self.phase_space_density.push(self.absimg.phase_space_density_1)
        self.gaussian_fit_centre_x.push(self.absimg.x0)
        self.gaussian_fit_centre_y.push(self.absimg.y0)
    
    #def get_default_analyses(self):
       # return [OnlineFit("line", data={"x": self.expansion_time, "y": self.sigmax_mm})]
 
 
        # self.ccb.issue(
        #     "create_applet",
        #     "AbsorptionImage",
        #     f"${{python}} -m repository.imaging.applet --server {server_addr}",  # noqa: E501,
        # )
AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)