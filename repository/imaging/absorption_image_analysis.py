from collections.abc import Iterable
from time import time
from ndscan.experiment import *

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us
from oitg.errorbars import binom_onesided
from scipy.optimize import curve_fit
import numpy as np

from ndscan.experiment import *

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
from ndscan.experiment.default_analysis import DefaultAnalysis, CustomAnalysis
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera, ROI
from repository.imaging.absorption_image import AbsorptionImageExpFrag
from repository.imaging.processor import AbsImage, AbsImageSettings  # noqa: E402
from repository.models.devices import SUServoedBeam
# from repository.Dipole_trap.moving_stage import MovingStage


class analysis_result(AbsorptionImageExpFrag):
    """Analysis for absorption imaging of MOT expansion"""

    def get_custom_analyses(self):
        return [
            CustomAnalysis(
                list([self.expansion_time]),
                self.Temperature,
                [FloatChannel("fit_t"), FloatChannel("fit_d")],
            )
        ]

    def Temperature(self, axis_values, result_values, analysis_result):
        # --- Constants ---
        kB = 1.380649e-23  # Boltzmann constant (J/K)
        m = 1.45e-25  # Mass (kg)
        # s = 1.62  # Pixel size in µm/pixel
        # delta_s = 0.18  # Uncertainty in pixel size

        t_data_sorted = np.array(axis_values[
            self.expansion_time.get()
        ])  # Get expansion time data
        d_data_sorted = np.array(result_values[self.sigmax_mm])  # Get atom number data

        # --- Model function ---
        def model(t, d0, T):
            return np.sqrt(d0**2 + (kB * T * t**2) / m)

        # --- Fit the data ---
        # NOTE: Replace or define your t_data_sorted and d_data_sorted arrays before fitting.
        # Example:
        # t_data_sorted = np.array([...])
        # d_data_sorted = np.array([...])

        bounds = ([0, 0], [np.inf, np.inf])
        p0 = [500e-6, 100e-6]  # Initial guess

        popt, pcov = curve_fit(
            model, t_data_sorted, d_data_sorted, p0=p0, bounds=bounds
        )
        d0_fit, T_fit = popt
        d0_err, T_err = np.sqrt(np.diag(pcov))

        t_fit = np.linspace(min(t_data_sorted), max(t_data_sorted), 300)
        d_fit = model(t_fit, *popt)

        analysis_result["fit_t"].push(t_fit)
        analysis_result["fit_d"].push(d_fit)
        # perr = np.sqrt(np.diag(pcov))
        # d_fit_upper = model(t_fit, *(popt + perr))
        # d_fit_lower = model(t_fit, *(popt - perr))

        return None


analysis_result = make_fragment_scan_exp(analysis_result)
