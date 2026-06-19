from asyncio.log import logger
from collections.abc import Iterable
from fileinput import filename
from time import time

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.suservo import SUServo
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us
from artiq.language.core import host_only
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
from ndscan.experiment.default_analysis import (
    DefaultAnalysis,
    OnlineFit,
    CustomAnalysis,
)
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera, camera_name, ROI
from repository.imaging.processor import AbsImage, AbsImageSettings  # noqa: E402
from repository.models.devices import SUServoedBeam
from repository.imaging.tekscope import TekscopeExp
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

        self.setattr_fragment(
            "pco_camera",
            PcoCamera,
            num_images=3,
        )
        self.pco_camera: PcoCamera

        self.setattr_fragment("tekscope", TekscopeExp, single_acquisition=True)
        self.tekscope: TekscopeExp

        # expsosure time for pcoedge cameras should be bigger than the imaging pulse because of camera has scan pixels line by line, like if we want to expose atoms for 100 us we should set the exposure time to be at least 150 us to make sure the whole cloud is exposed, for pixelfly camera which has global shutter we can set the exposure time to be the same as the imaging pulse duration.

        self.setattr_param_rebind(
            "exposure_time", self.pco_camera, "exposure_time", default=0.11 * ms
        )
        self.exposure_time: FloatParamHandle

        self.setattr_param_rebind(
            "camera_used", self.pco_camera, "camera_used", default=camera_name.FIRST
        )
        self.camera_used: ParamHandle

        self.mot: MOT = self.setattr_fragment("MOT", MOT, manual_init=False)
        self.suservo: SUServo = self.get_device("suservo")
        self.mot_voltages_temp = [0.0] * 10
        self.mot_voltages: OpaqueChannel = self.setattr_result(
            "mot_voltages", OpaqueChannel
        )

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
        # get the correct enum class based on the camera used
        self.setattr_param_rebind(
            "imaging_roi",
            self.pco_camera,
            "roi",
            default=ROI.FULL_pixelfly,
        )
        self.imaging_roi: ParamHandle

        self.use_tekscope: BoolParamHandle = self.setattr_param(
            "use_tekscope",
            BoolParam,
            "Whether to use the Tekscope for acquisition and saving",
            default=False,
            explanation="If False, the Tekscope will not be used for acquisition and saving. If True, a single acquisition will be performed on the Tekscope at the start of the experiment, and a screenshot and channel data will be saved. This is useful for debugging and monitoring the experiment, but may slow down the experiment if used in every run.",
        )

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
        self.phase_space_density: FloatChannel = self.setattr_result(
            "phase_space_density"
        )
        self.info: OpaqueChannel = self.setattr_result("info", OpaqueChannel)
        self.gaussian_fit_centre_x: FloatChannel = self.setattr_result(
            "gaussian_fit_centre_x"
        )
        self.gaussian_fit_centre_y: FloatChannel = self.setattr_result(
            "gaussian_fit_centre_y"
        )
        self.custom_objective: FloatChannel = self.setattr_result("custom_objective")
        self.tekscope_ch1: OpaqueChannel = self.setattr_result(
            "tekscope_ch1", OpaqueChannel
        )
        self.tekscope_ch2: OpaqueChannel = self.setattr_result(
            "tekscope_ch2", OpaqueChannel
        )
        self.tekscope_t: OpaqueChannel = self.setattr_result("tekscope_t", OpaqueChannel)

    @host_only
    def prepare(self) -> None:

        self.is_edge = self.camera_used.get() == camera_name.SECOND

        self.pco_edge_delay = self.pco_camera.trigger_delay

        self.camera_busy_time = self.pco_camera.camera_busy_time

        if self.is_edge:
            if self.expansion_time.get() < self.pco_edge_delay:
                raise ValueError(
                    "Expansion time must be at least 120 us to account "
                    "for the delay between trigger and exposure of the "
                    "PCO Edge camera."
                )

        if not self.is_edge:
            if self.imaging_roi.get() not in [
                ROI.FULL_pixelfly,
                ROI.MOT_pixelfly,
                ROI.ODT_Reservoir_pixelfly,
                ROI.ODT_Dimple_pixelfly,
            ]:
                raise ValueError("Invalid ROI selected for PIXELFLY camera.")

        return super().prepare()

    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.device_setup_subfragments()

    @kernel
    def run_once(self):
        self.core.break_realtime()
        self.mot.calculate_dma_handles()
        self.core.break_realtime()

        self.mot.set_dimple_trap_power(self.mot.power_dimple.get())
        # self.mot.set_reservoir_trap_power(self.mot.power_reservoir.get())

        self.mot.load(wait_for_load=False)
        # For debugging we want to monitor the mot photodiode while loading (suservo_ch0 adc)
        for i in range(10):
            self.mot_voltages_temp[i] = self.suservo.get_adc(0)
            delay(self.mot.loading_time.get() / 10.0)
        self.mot_voltages.push(self.mot_voltages_temp)

        if self.do_cmot.get():
            self.mot.compress(
                evaporation_active=self.do_evaporation1.get()
                or self.do_evaporation2.get(),
                odt_active=self.odt_active.get(),
            )
            if self.do_pgc.get():
                self.mot.pgc()

        self.mot.drop(
            evaporation_active=self.do_evaporation1.get() or self.do_evaporation2.get(),
            odt_active=self.odt_active.get(),
            cmot_active=self.do_cmot.get(),
            pgc_active=self.do_pgc.get(),
        )

        # if odt is active turn on odt beams
        if self.odt_active.get():
            delay(self.odt_hold_time.get())
            if not self.do_evaporation1.get() or self.do_evaporation2.get():
                self.mot.drop_dimple()
                self.mot.drop_reservoir()

        # Evaporation and then switch off odt beams
        if self.do_evaporation1.get():
            self.mot.evaporation1(
                single_step_evaporation=not self.do_evaporation2.get()
            )
            if self.do_evaporation2.get():
                self.mot.evaporation2()

        if self.is_edge:
            delay(
                self.expansion_time.get() - self.pco_edge_delay
            )  # pco edge camera has a delay of about ~120 us between the trigger and the start of the exposure
        else:
            delay(self.expansion_time.get())

        if self.is_edge:
            BUSY_TIME = self.camera_busy_time  # Hardcoding the busy time for pcedge
            # image cloud
            self.pco_camera.capture_image()
            delay(
                self.pco_edge_delay
            )  # wait for the camera to start exposing before turning on the imaging beams
            self.img_beam.turn_beams_on()
            delay(self.exposure_time.get())
            self.img_beam.turn_beams_off()
            self.mot.clear_atoms()  # takes 100ms
            delay(BUSY_TIME)

            # reference image
            self.pco_camera.capture_image()
            delay(self.pco_edge_delay)
            self.img_beam.turn_beams_on()
            delay(self.exposure_time.get())
            self.img_beam.turn_beams_off()
            delay(BUSY_TIME)

            # background image
            self.pco_camera.capture_image()
            delay(BUSY_TIME)

        # if pco pixelfy is used
        else:
            BUSY_TIME = self.camera_busy_time  # Hardcoding the busy time for pixelfly
            # image cloud
            with parallel:
                self.img_beam.turn_beams_on()
                self.pco_camera.capture_image()
            delay(self.exposure_time.get())
            self.img_beam.turn_beams_off()
            delay(1 * ms)
            # wait for the img pulse to dissipate before flushing atoms beams
            self.mot.clear_atoms(100 * ms)  # takes 100ms
            delay(BUSY_TIME - self.exposure_time.get() - 101 * ms)

            # reference image
            with parallel:
                self.img_beam.turn_beams_on()
                self.pco_camera.capture_image()
            delay(self.exposure_time.get())
            self.img_beam.turn_beams_off()
            delay(BUSY_TIME - self.exposure_time.get())

            # background image
            self.pco_camera.capture_image()
            delay(BUSY_TIME)

        # leave the MOT to reload
        self.mot.init()
        self.mot.load(wait_for_load=False)

        self.core.wait_until_mu(now_mu())
        self.update_images()

        if self.use_tekscope.get():
            self.save_tekscope_screenshot_csv()
        else:
            pass

    @rpc(flags={"async"})
    def save_tekscope_screenshot_csv(self):

        wf = self.tekscope.get_waveform_artiq("CH1")
        time_axis = wf["time"]
        wf2 = self.tekscope.get_waveform_artiq("CH2")
        self.tekscope_ch1.push(wf["voltage"])
        self.tekscope_ch2.push(wf2["voltage"])
        self.tekscope_t.push(time_axis)

    @rpc(flags={"async"})
    def update_images(self):
        images = self.pco_camera.retrieve_images(
            roi=self.imaging_roi.get(), timeout=1.0 * s
        )
        if images is None:
            raise RuntimeError("Failed to retrieve images from camera")

        for num, img_name in enumerate(["TOF", "REF", "BG"]):
            # save for applet
            self.set_dataset(
                f"Images.absorption.{img_name}",
                np.asarray(images[num], dtype=np.uint16),
                broadcast=True,
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

        # # Custom objective 1 : # symmetric cloud
        # self.custom_objective.push(abs(self.absimg.sigmax - self.absimg.sigmay))

        # Custom objective 2 : # maximizing atom number
        self.custom_objective.push(1e9 - self.absimg.atom_number)

        # ensure that every image in a scan is saved for later analysis
        # using uint16 saves about 4x space since pixels are easily 0-65,535 anyway
        # self.all_images.push(np.asarray(images, dtype=np.uint16))

        # Volume of the cloud assuming Gaussian distribution, 3D
        # V = (2π)^(3/2) σx σy σz
        V = (
            (2 * np.pi) ** (3 / 2)
            * self.absimg.sigmax
            * self.absimg.sigmay
            * self.absimg.sigmax  # σz = σx
        )

        # Number density
        n = self.absimg.atom_number / V

        alpha = 0.5  # weight for atom no. density
        # Custom objective 3 : # maximizing number density & atom number
        # self.custom_objective.push(
        #     -1 * ((alpha * (n / 1e11)) + (1 - alpha) * (self.absimg.atom_number / 1e9))
        # )

        # Custom objective 4 : #number density
        # self.custom_objective.push(1e11 - n)

        # Custom objective 5 : # maximizing PSD
        # self.custom_objective.push(
        #     1e-4 - self.absimg.phase_space_density_1)

    # def get_default_analyses(self):
    # return [OnlineFit("line", data={"x": self.expansion_time, "y": self.sigmax_mm})]

    # self.ccb.issue(
    #     "create_applet",
    #     "AbsorptionImage",
    #     f"${{python}} -m repository.imaging.applet --server {server_addr}",  # noqa: E501,
    # )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
