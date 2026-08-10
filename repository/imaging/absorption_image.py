import logging
from time import time

import numpy as np
from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.suservo import SUServo
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import EnumerationValue, kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, sequential, us
from artiq.language.core import host_only

# from repository.models.device_db import server_addr
from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    OpaqueChannel,
    RestartKernelTransitoryError,
    make_fragment_scan_exp,
)
from ndscan.experiment.annotations import curve_1d
from ndscan.experiment.default_analysis import CustomAnalysis
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle

from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.analysis import fit_gravity, fit_temperature
from repository.imaging.PCO_Camera import ROI, PcoCamera, camera_name
from repository.imaging.processor import AbsImage, AbsImageSettings
from repository.models.devices import SUServoedBeam

logger = logging.getLogger(__name__)

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
            default=0.227,  # calibrated 27/06/2026 rid28410 + rid28411
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
            "do_cmot", BoolParam, "Do the CMOT step", default=True
        )

        self.do_pgc: BoolParamHandle = self.setattr_param(
            "do_pgc", BoolParam, "Do the PGC step", default=True
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
        # self.mot_voltages.push(self.mot_voltages_temp)

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
        with parallel:
            delay(self.camera_busy_time)
            with sequential:
                delay(self.exposure_time.get())
                self.mot.clear_atoms(50 * ms)

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

    @rpc
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

        self.absimg = AbsImage(
            data=images[0],
            ref=images[1],
            bg=images[2],
            settings=settings,
        )

        # If the image seems invalid dont log it
        if self.absimg.atom_number < 0.0 or self.absimg.fit.summary()["rsquared"] < 0.7:
            logger.error("No atoms detected - Fix and retry from Interactive Args")
            with self.interactive(title="Zero atoms detected; retry?") as interactive:
                interactive.setattr_argument(
                    "retry",
                    EnumerationValue(
                        ["Retry", "Use point", "Abort"], "Retry", quickstyle=True
                    ),
                    tooltip="Check the laser is locked then confirm to retry the point",
                )
            if interactive.retry == "Retry":
                raise RestartKernelTransitoryError("No atoms detected; retrying")
            if interactive.retry == "Abort":
                raise RuntimeError("Scan aborted after a failed point")

        # This indicates a valid image for the website
        self.set_dataset(
            "Images.absorption.timestamp",
            time(),
            broadcast=True,
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
        N_ref = 1.11e8  # current atom number
        sigma_0_x = 1.7  # σₓ (mm)
        sigma_0_y = 1.14  # σᵧ (mm)
        sigma_x = self.absimg.sigmax * self.absimg.physical_scale * 1e3
        sigma_y = self.absimg.sigmay * self.absimg.physical_scale * 1e3
        exponent = 2.0  # Exponent for the size terms

        # Custom objective 2 :
        if self.absimg.atom_number <= 0:
            # Push a large value to penalize zero atom number
            self.custom_objective.push(1)
        else:
            self.custom_objective.push(
                -np.log(self.absimg.atom_number / N_ref)
                + exponent * (np.log(sigma_x / sigma_0_x) + np.log(sigma_y / sigma_0_y))
            )

    def get_default_analyses(self):
        return [
            CustomAnalysis(
                [self.expansion_time],
                self._analyse_tof_benchmark,
                [
                    FloatChannel("atom_number_mean"),
                    FloatChannel("atom_number_std"),
                    FloatChannel("temperature_x", unit="K", scale=1),
                    FloatChannel("temperature_x_err", unit="K", scale=1),
                    FloatChannel("temperature_y", unit="K", scale=1),
                    FloatChannel("temperature_y_err", unit="K", scale=1),
                    FloatChannel("sigma0_x", unit="um", scale=1e-6),
                    FloatChannel("sigma0_y", unit="um", scale=1e-6),
                    FloatChannel(
                        "magnification_pixel_size",
                        unit="um/px",
                        scale=1e-6,
                    ),
                    FloatChannel(
                        "gravity_pixel_size",
                        unit="um/px",
                        scale=1e-6,
                    ),
                    FloatChannel(
                        "gravity_pixel_size_err",
                        unit="um/px",
                        scale=1e-6,
                    ),
                    FloatChannel(
                        "gravity_initial_velocity_y",
                        unit="mm/s",
                        scale=1e-3,
                    ),
                    OpaqueChannel("fit_time", "Fit time (s)"),
                ],
            )
        ]

    def _analyse_tof_benchmark(self, axis_values, result_values, analysis_result):
        times = np.asarray(axis_values[self.expansion_time], dtype=float)
        atom_numbers = np.asarray(result_values[self.atom_number], dtype=float)

        if atom_numbers.size:
            atom_number_mean = np.mean(atom_numbers)
            atom_number_std = np.std(atom_numbers)
        else:
            atom_number_mean = atom_number_std = np.nan
        analysis_result["atom_number_mean"].push(atom_number_mean)
        analysis_result["atom_number_std"].push(atom_number_std)

        pixel_size = AbsImageSettings.pixel_size / self.magnification.get()
        analysis_result["magnification_pixel_size"].push(pixel_size)

        temperature_results = {}
        for label, channel in (("x", self.sigmax), ("y", self.sigmay)):
            result = fit_temperature(times, result_values[channel], pixel_size)
            temperature_results[label] = result
            if result is None:
                result = {
                    "fit_params": (np.nan, np.nan),
                    "sigma0": np.nan,
                    "temperature": np.nan,
                    "temperature_error": np.nan,
                }

            analysis_result[f"temperature_{label}"].push(result["temperature"])
            analysis_result[f"temperature_{label}_err"].push(
                result["temperature_error"]
            )
            analysis_result[f"sigma0_{label}"].push(result["sigma0"])

        finite_times = times[np.isfinite(times) & (times >= 0)]
        if finite_times.size:
            fit_times = np.linspace(0.0, float(np.max(finite_times)), 300)
        else:
            fit_times = np.array([])
        analysis_result["fit_time"].push(fit_times)
        temperature_fit_sigmas = {}
        for label in ("x", "y"):
            result = temperature_results[label]
            if result is None:
                continue
            sigma0_squared, sigma_v_squared = result["fit_params"]
            temperature_fit_sigmas[label] = np.sqrt(
                sigma0_squared + sigma_v_squared * fit_times**2
            )

        gravity_result = fit_gravity(
            times,
            result_values[self.gaussian_fit_centre_y],
        )
        if gravity_result is not None:
            gravity_times = fit_times
            gravity_position = np.polyval(gravity_result["fit_params"], gravity_times)
        else:
            gravity_result = {
                "pixel_size": np.nan,
                "pixel_size_error": np.nan,
                "initial_velocity": np.nan,
            }
            gravity_times = np.array([])
            gravity_position = np.array([])

        gravity_pixel_size = gravity_result["pixel_size"]
        gravity_pixel_size_error = gravity_result["pixel_size_error"]
        if np.isfinite(gravity_pixel_size) and np.isfinite(gravity_pixel_size_error):
            agrees = bool(
                abs(gravity_pixel_size - pixel_size) <= 3.0 * gravity_pixel_size_error
            )
            if not agrees:
                logger.warning(
                    "Magnification pixel size %.4g m does not agree with the gravity"
                    " fit %.4g +/- %.2g m",
                    pixel_size,
                    gravity_pixel_size,
                    gravity_pixel_size_error,
                )

        analysis_result["gravity_pixel_size"].push(gravity_pixel_size)
        analysis_result["gravity_pixel_size_err"].push(gravity_pixel_size_error)
        analysis_result["gravity_initial_velocity_y"].push(
            gravity_result["initial_velocity"]
        )
        annotations = []
        for label, channel in (("x", self.sigmax), ("y", self.sigmay)):
            if label in temperature_fit_sigmas:
                annotations.append(
                    curve_1d(
                        self.expansion_time,
                        analysis_result["fit_time"],
                        channel,
                        temperature_fit_sigmas[label],
                    )
                )
        if gravity_times.size:
            annotations.append(
                curve_1d(
                    self.expansion_time,
                    analysis_result["fit_time"],
                    self.gaussian_fit_centre_y,
                    gravity_position,
                )
            )
        return annotations


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
