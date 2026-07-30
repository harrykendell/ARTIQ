"""Benchmark experiments for the main MOT-to-ODT sequence."""

import logging

import numpy as np
from artiq.language.units import ms, s
from ndscan.experiment import (
    FloatChannel,
    OpaqueChannel,
)
from ndscan.experiment.annotations import Annotation
from ndscan.experiment.default_analysis import CustomAnalysis
from scipy import constants
from scipy.optimize import curve_fit

from repository.benchmark.common import make_benchmark_scan_exp
from repository.imaging.absorption_image import AbsorptionImageExpFrag
from repository.imaging.processor import AbsImageSettings

logger = logging.getLogger(__name__)

MOT_TOF_TIMES = tuple(value * ms for value in range(16))
CMOT_TOF_TIMES = tuple(value * ms for value in range(4, 16))
PGC_TOF_TIMES = tuple(value * ms for value in range(4, 31))
ODT_TOF_TIMES = (0.5 * ms,) + tuple(value * ms for value in range(1, 31))

TOF_LOADING_TIME = 10 * s
RB87_MASS = 86.909180520 * constants.atomic_mass


def _analysis_result_curve_1d(x_axis, x_values, y_axis, y_values):
    """Build a curve annotation backed by archived analysis-result channels.

    ``curve_1d()`` normalises its values as concrete sequences in the ndscan
    version used here, so construct the equivalent public annotation directly
    to retain references to the analysis-result datasets.
    """
    return Annotation(
        "curve",
        coordinates={
            x_axis: x_values,
            y_axis: y_values,
        },
    )


def _fit_temperature(times, sigma_px, pixel_size):
    """Fit sigma squared against TOF squared, following temp_pixel 2D.ipynb."""
    times = np.asarray(times, dtype=float)
    sigma_px = np.asarray(sigma_px, dtype=float)
    valid = np.isfinite(times) & np.isfinite(sigma_px) & (times >= 0) & (sigma_px > 0)
    times = times[valid]
    sigma_px = sigma_px[valid]
    if times.size < 3 or np.unique(times).size < 2:
        raise ValueError("Not enough valid TOF points for a temperature fit")

    time_squared = times**2
    sigma_squared = sigma_px**2
    time_span = max(float(np.ptp(time_squared)), 1e-12)
    initial = [
        max(0.0, float(np.min(sigma_squared))),
        max(1e-12, float(np.ptp(sigma_squared)) / time_span),
    ]

    def sigma_squared_model(t_squared, sigma0_px_squared, sigma_v_px_squared):
        return sigma0_px_squared + sigma_v_px_squared * t_squared

    fit_params, covariance = curve_fit(
        sigma_squared_model,
        time_squared,
        sigma_squared,
        p0=initial,
        bounds=([0.0, 0.0], [np.inf, np.inf]),
    )

    sigma0_px_squared, sigma_v_px_squared = fit_params
    temperature = RB87_MASS * sigma_v_px_squared * pixel_size**2 / constants.Boltzmann

    slope_variance = covariance[1, 1]
    if np.isfinite(slope_variance) and sigma_v_px_squared > 0:
        temperature_error = temperature * np.sqrt(slope_variance) / sigma_v_px_squared
    else:
        temperature_error = np.nan

    return {
        "fit_params": fit_params,
        "sigma0": np.sqrt(sigma0_px_squared) * pixel_size,
        "temperature": temperature,
        "temperature_error": temperature_error,
    }


def _fit_gravity(times, position_y_px):
    """Infer an object-plane pixel scale from vertical free fall."""
    times = np.asarray(times, dtype=float)
    position_y_px = np.asarray(position_y_px, dtype=float)
    valid = np.isfinite(times) & np.isfinite(position_y_px) & (times >= 0)
    times = times[valid]
    position_y_px = position_y_px[valid]
    if times.size < 4 or np.unique(times).size < 3:
        raise ValueError("Not enough valid TOF points for a gravity fit")

    gravity = constants.g

    def fall_y(t, pixels_per_metre, y0, vy0):
        return y0 + vy0 * t - 0.5 * gravity * pixels_per_metre * t**2

    quadratic = np.polyfit(times, position_y_px, 2)
    initial_pixels_per_metre = max(
        1.0,
        abs(-2.0 * quadratic[0] / gravity),
    )
    fit_params, covariance = curve_fit(
        fall_y,
        times,
        position_y_px,
        p0=[initial_pixels_per_metre, quadratic[2], quadratic[1]],
        bounds=([0.0, -np.inf, -np.inf], [np.inf, np.inf, np.inf]),
    )

    pixels_per_metre, _, velocity_px_per_s = fit_params
    pixels_per_metre_error = (
        np.sqrt(covariance[0, 0]) if np.isfinite(covariance[0, 0]) else np.nan
    )
    pixel_size = 1.0 / pixels_per_metre
    pixel_size_error = (
        pixels_per_metre_error / pixels_per_metre**2
        if np.isfinite(pixels_per_metre_error)
        else np.nan
    )

    return {
        "fit_params": fit_params,
        "model": fall_y,
        "pixel_size": pixel_size,
        "pixel_size_error": pixel_size_error,
        "initial_velocity": velocity_px_per_s / pixels_per_metre,
    }


class _TOFBenchmarkExpFrag(AbsorptionImageExpFrag):
    """Common absorption-image specialisation used by the TOF benchmarks."""

    DO_CMOT = False
    DO_PGC = False
    ODT_ACTIVE = False

    def build_fragment(self):
        super().build_fragment()

        self.override_param("do_cmot", self.DO_CMOT)
        self.override_param("do_pgc", self.DO_PGC)
        self.override_param("trap_frequency", False)
        self.override_param("ODT_active", self.ODT_ACTIVE)
        self.override_param("do_evaporation1", False)
        self.override_param("do_evaporation2", False)
        self.mot.override_param("loading_time", TOF_LOADING_TIME)

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
                    OpaqueChannel(
                        "temperature_fit_time",
                        "Temperature fit time (s)",
                    ),
                    OpaqueChannel(
                        "temperature_fit_sigma_x",
                        "Horizontal temperature fit sigma (px)",
                    ),
                    OpaqueChannel(
                        "temperature_fit_sigma_y",
                        "Vertical temperature fit sigma (px)",
                    ),
                    OpaqueChannel(
                        "gravity_fit_time",
                        "Gravity fit time (s)",
                    ),
                    OpaqueChannel(
                        "gravity_fit_position_y",
                        "Gravity fit vertical position (px)",
                    ),
                    OpaqueChannel(
                        "gravity_fit_residual_y",
                        "Gravity fit vertical residual (px)",
                    ),
                    OpaqueChannel("pixel_size_agrees_with_gravity"),
                ],
            )
        ]

    def _analyse_tof_benchmark(self, axis_values, result_values, analysis_result):
        times = np.asarray(axis_values[self.expansion_time], dtype=float)
        atom_numbers = np.asarray(result_values[self.atom_number], dtype=float)
        valid = atom_numbers[np.isfinite(atom_numbers) & (atom_numbers > 0)]

        if valid.size:
            mean = float(np.mean(valid))
            std = float(np.std(valid))
        else:
            mean = np.nan
            std = np.nan

        analysis_result["atom_number_mean"].push(mean)
        analysis_result["atom_number_std"].push(std)

        pixel_size = AbsImageSettings.pixel_size / self.magnification.get()
        analysis_result["magnification_pixel_size"].push(pixel_size)

        temperature_results = {}
        for label, channel in (("x", self.sigmax), ("y", self.sigmay)):
            try:
                temperature_results[label] = _fit_temperature(
                    times,
                    result_values[channel],
                    pixel_size,
                )
            except Exception:
                logger.warning(
                    "%s temperature fit failed",
                    label,
                    exc_info=True,
                )
                temperature_results[label] = {
                    "fit_params": np.array([np.nan, np.nan]),
                    "sigma0": np.nan,
                    "temperature": np.nan,
                    "temperature_error": np.nan,
                }

            result = temperature_results[label]
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
        analysis_result["temperature_fit_time"].push(fit_times)
        temperature_fit_sigmas = {}
        for label in ("x", "y"):
            sigma0_squared, sigma_v_squared = temperature_results[label]["fit_params"]
            temperature_fit_sigmas[label] = np.sqrt(
                sigma0_squared + sigma_v_squared * fit_times**2
            )
            analysis_result[f"temperature_fit_sigma_{label}"].push(
                temperature_fit_sigmas[label]
            )

        try:
            gravity_result = _fit_gravity(
                times,
                result_values[self.gaussian_fit_centre_y],
            )
            gravity_times = fit_times
            gravity_position = gravity_result["model"](
                gravity_times,
                *gravity_result["fit_params"],
            )
            measured_position = np.asarray(
                result_values[self.gaussian_fit_centre_y],
                dtype=float,
            )
            gravity_residual = measured_position - gravity_result["model"](
                times,
                *gravity_result["fit_params"],
            )
        except Exception:
            logger.warning("Gravity pixel-scale fit failed", exc_info=True)
            gravity_result = {
                "pixel_size": np.nan,
                "pixel_size_error": np.nan,
                "initial_velocity": np.nan,
            }
            gravity_times = np.array([])
            gravity_position = np.array([])
            gravity_residual = np.array([])

        gravity_pixel_size = gravity_result["pixel_size"]
        gravity_pixel_size_error = gravity_result["pixel_size_error"]
        agrees = False
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
        analysis_result["gravity_fit_time"].push(gravity_times)
        analysis_result["gravity_fit_position_y"].push(gravity_position)
        analysis_result["gravity_fit_residual_y"].push(gravity_residual)
        analysis_result["pixel_size_agrees_with_gravity"].push(agrees)

        annotations = []
        for label, channel in (("x", self.sigmax), ("y", self.sigmay)):
            if np.any(np.isfinite(temperature_fit_sigmas[label])):
                annotations.append(
                    _analysis_result_curve_1d(
                        self.expansion_time,
                        analysis_result["temperature_fit_time"],
                        channel,
                        analysis_result[f"temperature_fit_sigma_{label}"],
                    )
                )
        if gravity_times.size:
            annotations.append(
                _analysis_result_curve_1d(
                    self.expansion_time,
                    analysis_result["gravity_fit_time"],
                    self.gaussian_fit_centre_y,
                    analysis_result["gravity_fit_position_y"],
                )
            )
        return annotations


class MOTBenchFragment(_TOFBenchmarkExpFrag):
    """MOT"""

    DO_CMOT = False
    DO_PGC = False
    ODT_ACTIVE = False
    TOF_TIMES = MOT_TOF_TIMES


class CMOTBenchFragment(_TOFBenchmarkExpFrag):
    """CMOT"""

    DO_CMOT = True
    DO_PGC = False
    ODT_ACTIVE = False
    TOF_TIMES = CMOT_TOF_TIMES


class PGCBenchFragment(_TOFBenchmarkExpFrag):
    """PGC"""

    DO_CMOT = True
    DO_PGC = True
    ODT_ACTIVE = False
    TOF_TIMES = PGC_TOF_TIMES


class ODTBenchFragment(_TOFBenchmarkExpFrag):
    """ODT"""

    DO_CMOT = True
    DO_PGC = True
    ODT_ACTIVE = True
    TOF_TIMES = ODT_TOF_TIMES


MOTBench = make_benchmark_scan_exp(
    "MOTBench",
    MOTBenchFragment,
)
CMOTBench = make_benchmark_scan_exp(
    "CMOTBench",
    CMOTBenchFragment,
)
PGCBench = make_benchmark_scan_exp(
    "PGCBench",
    PGCBenchFragment,
)
ODTBench = make_benchmark_scan_exp(
    "ODTBench",
    ODTBenchFragment,
)
