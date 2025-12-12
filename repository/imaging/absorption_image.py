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
 
from artiq.coredevice.ttl import TTLInOut
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera
from repository.imaging.processor import AbsImage  # noqa: E402
from repository.models.devices import SUServoedBeam
from repository.Dipole_trap.moving_stage import MovingStage
 
MAGNIFICATION = 1  # Default magnification for absorption imaging
 
 
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
 
        self.setattr_fragment("absolute_moving_stage", MovingStage)
        self.absolute_moving_stage: MovingStage
 
        self.setattr_param_rebind(
            "moving_absolute_distance",
            self.absolute_moving_stage,
            "moving_absolute_distance",
            default=1.0,
        )
        self.moving_absolute_distance: FloatParamHandle
 
        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=0.5 * ms,
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
 
        if self.odt_active.get() or self.do_evaporation1.get() or self.do_evaporation2.get():
              self.mot.set_dimple_trap_power(self.mot.power_dimple.get())
              self.mot.set_reservoir_trap_power(self.mot.power_reservoir.get())
 
        # self.mot.odt_reservoir.turn_beams_on()
        # self.mot.odt_dimple.turn_beams_on()
        # self.mot.cpt_shutter.off()
        #self.absolute_moving_stage.set_stage_absolute(20.455, 0)
        #self.absolute_moving_stage.move_stage_absolute()
        #delay(1 * s)
        # move stage to imaging position
        # self.moving_stage_trigger.pulse(10 * us)  # trigger moving stage
 
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
 
 
AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
 