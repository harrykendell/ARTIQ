from time import time

import numpy as np
from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.suservo import SUServo
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us
from artiq.language.core import host_only

# from repository.models.device_db import server_addr
from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    OpaqueChannel,
    make_fragment_scan_exp,
)
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle

from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import ROI, PcoCamera, camera_name
from repository.imaging.processor import AbsImage, AbsImageSettings
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

        self.setattr_fragment(
            "pco_camera",
            PcoCamera,
            num_images=3,
        )
        self.pco_camera: PcoCamera

        # expsosure time for pcoedge cameras should be bigger than the imaging pulse because of camera has scan pixels line by line, like if we want to expose atoms for 100 us we should set the exposure time to be at least 150 us to make sure the whole cloud is exposed, for pixelfly camera which has global shutter we can set the exposure time to be the same as the imaging pulse duration.

        self.setattr_param_rebind(
            "exposure_time", self.pco_camera, "exposure_time", default=0.03 * ms
        )
        self.exposure_time: FloatParamHandle

        self.setattr_param_rebind(
            "camera_used", self.pco_camera, "camera_used", default=camera_name.PIXELFLY
        )
        self.camera_used: ParamHandle

        self.mot: MOT = self.setattr_fragment("MOT", MOT, manual_init=False)
        self.suservo: SUServo = self.get_device("suservo")
        # self.mot_voltages_temp = [0.0] * 10
        # self.mot_voltages: OpaqueChannel = self.setattr_result(
        #     "mot_voltages", OpaqueChannel
        # )

        self.img_beam: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "img_beam", ControlBeamsWithoutCoolingAOM, [SUServoedBeam["IMG"]]
        )

        self.setattr_device("scope_trigger")
        self.scope_trigger: TTLInOut = self.scope_trigger

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
            default=0.29,
        )
        self.magnification: FloatParamHandle

        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=25 * ms,
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
            default=ROI.MOT_pixelfly,
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
            default=100.0 * ms,
            min=0.0 * ms,
            unit="ms",
        )

        self.atom_number: FloatChannel = self.setattr_result("atom_number")
        self.sigmax_mm: FloatChannel = self.setattr_result("sigmax_mm")
        self.sigmay_mm: FloatChannel = self.setattr_result("sigmay_mm")
        self.sigmax: FloatChannel = self.setattr_result("sigmax")
        self.sigmay: FloatChannel = self.setattr_result("sigmay")
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

        self.peak_od: FloatChannel = self.setattr_result("peak_od")

    @host_only
    def prepare(self) -> None:
        self.is_edge = self.camera_used.get() == camera_name.EDGE

        self.camera_busy_time = self.pco_camera.camera_busy_time

        if self.expansion_time.get() < self.pco_camera.trigger_delay:
            raise ValueError(
                f"Expansion time must be at least {self.pco_camera.trigger_delay}s to account "
                "for the delay between trigger and exposure of the camera."
            )

        if not self.is_edge and self.imaging_roi.get() not in [
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

        # self.mot.set_dimple_trap_power(self.mot.power_dimple.get())
        # self.mot.set_reservoir_trap_power(self.mot.power_reservoir.get())

        self.mot.load(wait_for_load=False)
        # Eventualy try stabilising atom number noise by triggering off the mot photodiode while loading (suservo_ch0 adc)
        # for i in range(10):
        #     # self.mot_voltages_temp[i] = self.suservo.get_adc(0)
        #     delay(self.mot.loading_time.get() / 10.0)
        # # self.mot_voltages.push(self.mot_voltages_temp)
        delay(self.mot.loading_time.get())

        if self.do_cmot.get():
            self.mot.compress(
                evaporation_active=self.do_evaporation1.get()
                or self.do_evaporation2.get(),
                odt_active=self.odt_active.get(),
                power_dimple=self.mot.power_dimple.get(),
                power_reservoir=self.mot.power_reservoir.get(),
            )
            if self.do_pgc.get():
                self.mot.pgc()

        self.mot.drop(
            evaporation_active=self.do_evaporation1.get() or self.do_evaporation2.get(),
            odt_active=self.odt_active.get(),
        )

        # if odt is active turn on odt beams
        if self.odt_active.get():
            delay(self.odt_hold_time.get())
            if not (self.do_evaporation1.get() or self.do_evaporation2.get()):
                self.mot.odt_dimple.off()
                self.mot.odt_reservoir.off()

        # Evaporation and then switch off odt beams
        if self.do_evaporation1.get():
            self.mot.evaporation1(
                single_step_evaporation=not self.do_evaporation2.get()
            )
            if self.do_evaporation2.get():
                self.mot.evaporation2()

        delay(self.expansion_time.get())

        # THE 3 IMAGES FOR ABSORPTION IMAGING

        # TODO: This is a hack to clear background atoms around the ODT for the edge camera
        # probably needs removing or doing more robustly
        # if self.is_edge:
        #     self.mot.clear_background_atoms_around_odt()

        # TOF IMAGE
        self.pco_camera.capture_image()
        self.img_beam.on()
        delay(self.exposure_time.get())
        self.img_beam.off()

        # wait for the img pulse to dissipate before flushing atoms beams
        with parallel:  # timeline advances by max(100ms, camera_busy_time)
            delay(self.camera_busy_time)
            self.mot.clear_atoms(100 * ms)

        # REF IMAGE
        self.pco_camera.capture_image()
        self.img_beam.on()
        delay(self.exposure_time.get())
        self.img_beam.off()
        delay(self.camera_busy_time)

        # BG IMAGE
        self.pco_camera.capture_image()
        delay(self.camera_busy_time)

        # leave the MOT to reload
        self.mot.init()
        self.mot.load(wait_for_load=False)

        self.core.wait_until_mu(now_mu())
        self.update_images()

    @rpc(flags={"async"})
    def update_images(self):
        # print roi for debugging
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

        settings = AbsImageSettings(
            magnification=self.magnification.get(),
            time_of_flight=self.expansion_time.get(),
        )  # Set default magnification

        self.set_dataset(
            "Images.absorption.settings",
            settings.to_dataset(),
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
            settings=settings,
        )

        self.atom_number.push(self.absimg.atom_number)
        self.info.push(self.absimg.all_info())
        self.sigmax.push(self.absimg.sigmax)
        self.sigmay.push(self.absimg.sigmay)
        self.sigmax_mm.push(self.absimg.sigmax * self.absimg.physical_scale * 1e3)
        self.sigmay_mm.push(self.absimg.sigmay * self.absimg.physical_scale * 1e3)
        self.phase_space_density.push(self.absimg.phase_space_density_1)
        self.gaussian_fit_centre_x.push(self.absimg.x0)
        self.gaussian_fit_centre_y.push(self.absimg.y0)
        self.peak_od.push(self.absimg.peak_od)

        # Reference values for normalization
        N_ref = 2e8  # current atom number
        sigma_0_x = 1.70  # σₓ (mm)
        sigma_0_y = 1.55  # σᵧ (mm)
        sigma_x = self.absimg.sigmax * self.absimg.physical_scale * 1e3
        sigma_y = self.absimg.sigmay * self.absimg.physical_scale * 1e3
        exponent = 1.5  # Exponent for the size terms

        # Custom objective 2 :
        if self.absimg.atom_number <= 0:
            # Push a large value to penalize zero atom number
            self.custom_objective.push(1)
        else:
            self.custom_objective.push(
                -np.log(self.absimg.atom_number / N_ref)
                + exponent * (np.log(sigma_x / sigma_0_x) + np.log(sigma_y / sigma_0_y))
            )

        # def get_default_analyses(self):
        # return [OnlineFit("line", data={"x": self.expansion_time, "y": self.sigmax})]

        # self.ccb.issue(
        #     "create_applet",
        #     "AbsorptionImage",
        #     f"${{python}} -m repository.imaging.applet --server {server_addr}",
        # )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
