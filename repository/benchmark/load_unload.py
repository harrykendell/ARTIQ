"""Benchmark experiments for the main MOT-to-ODT sequence."""

import logging

import numpy as np
from artiq.coredevice.core import Core
from artiq.experiment import (
    kernel,
    rpc,
)
from artiq.language.core import delay, delay_mu
from artiq.language.units import ms, s
from artiq.master.worker_impl import CCB
from ndscan.experiment import (
    ExpFragment,
    FloatChannel,
    FloatParam,
    IntParam,
    OpaqueChannel,
)
from ndscan.experiment.parameters import FloatParamHandle, IntParamHandle

from repository.benchmark.common import make_benchmark_scan_exp
from repository.benchmark.exponential_load_fit import exponential_load
from repository.fragments.mot import MOT
from repository.fragments.read_adc import ReadSUServoADC
from repository.models.device_db import server_addr
from submodules.oitg.oitg.fitting import exponential_decay

logger = logging.getLogger(__name__)


class LoadUnloadBenchFragment(ExpFragment):
    """Loading and lifetime"""

    DATASET_PREFIX = "benchmark.load_unload"

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")
        self.ccb: CCB

        self.mot: MOT = self.setattr_fragment("MOT", MOT, manual_init=False)
        self.loading_time: FloatParamHandle = self.setattr_param_rebind(
            "loading_time",
            self.mot,
            "loading_time",
            default=90 * s,
        )

        self.setattr_param(
            "unloading_time",
            FloatParam,
            "Time to record the MOT decay after closing the 2D shutter",
            default=90 * s,
            unit="s",
        )
        self.unloading_time: FloatParamHandle

        self.setattr_param(
            "trace_points",
            IntParam,
            "Number of samples in the trace",
            default=1000,
            min=4,
        )
        self.trace_points: IntParamHandle

        self.adc_reader: ReadSUServoADC = self.setattr_fragment(
            "adc_reader",
            ReadSUServoADC,
            self.get_device("MOT_photodiode"),
        )

        self.voltages: OpaqueChannel = self.setattr_result("voltages", OpaqueChannel)
        self.time: OpaqueChannel = self.setattr_result("time", OpaqueChannel)
        self.fit: OpaqueChannel = self.setattr_result("fit", OpaqueChannel)
        self.load_time_constant: FloatChannel = self.setattr_result(
            "load_time_constant", FloatChannel
        )
        self.unload_time_constant: FloatChannel = self.setattr_result(
            "unload_time_constant", FloatChannel
        )

    @kernel
    def device_setup(self):
        self.core.reset()
        self.device_setup_subfragments()

    @kernel
    def run_once(self):
        data = [0.0] * self.trace_points.get()

        interval_mu = self.core.seconds_to_mu(
            (self.loading_time.get() + self.unloading_time.get())
            / (self.trace_points.get() - 1)
        )

        self.core.break_realtime()

        self.mot.load(wait_for_load=False)
        delay(self.loading_time.get())
        self.mot.shutter_2d.off()
        delay(-self.loading_time.get() + 1 * ms)

        for i in range(self.trace_points.get()):
            data[i] = self.adc_reader.read_adc()
            delay_mu(interval_mu)

        # leave the MOT to reload
        self.mot.shutter_2d.on()

        self.archive_traces(
            data,
            interval_mu,
        )

    @rpc
    def archive_traces(
        self,
        data,
        interval_mu,
    ):
        trace = np.asarray(data, dtype=float)
        interval = self.core.mu_to_seconds(interval_mu)
        time = np.arange(trace.size) * interval

        fit, load_tau, unload_tau = self._fit_trace(time, trace)

        self.voltages.push(trace)
        self.time.push(time)
        self.fit.push(fit)
        self.load_time_constant.push(load_tau)
        self.unload_time_constant.push(unload_tau)

        datasets = {
            "trace": trace,
            "time_axis": time,
            "fit": fit,
            "loading_time_constant": load_tau,
            "unloading_time_constant": unload_tau,
            "sample_interval": interval,
        }
        for name, value in datasets.items():
            self.set_dataset(
                f"{self.DATASET_PREFIX}.{name}",
                value,
                broadcast=True,
                persist=True,
                unit="V" if name in ["trace", "fit"] else "s",
            )

        self.ccb.issue(
            "create_applet",
            "MOT loading/unloading trace",
            f"${{artiq_applet}}plot_xy {self.DATASET_PREFIX}.trace"
            f" --x {self.DATASET_PREFIX}.time_axis"
            f" --fit {self.DATASET_PREFIX}.fit"
            f" --title 'Loading = {load_tau:.3g} s, Unloading = {unload_tau:.3g} s'"
            f" --server {server_addr}",
            group="benchmark",
        )

    def _fit_trace(self, time_axis, trace):

        # Index where the 2D shutter is closed.
        switch_idx = np.searchsorted(time_axis, self.loading_time.get())

        # Need enough points on each side to perform a fit.
        if switch_idx < 4 or (len(trace) - switch_idx) < 4:
            return np.full_like(trace, np.nan), np.nan, np.nan

        # --------------------
        # Loading fit
        # --------------------

        t_load = time_axis[:switch_idx] - time_axis[0]
        y_load = np.asarray(trace[:switch_idx])

        # --------------------
        # Unloading fit
        # --------------------

        t_unload = time_axis[switch_idx:] - time_axis[switch_idx]
        y_unload = np.asarray(trace[switch_idx:])

        try:
            load_results, _, _, load_fit = exponential_load.fit(
                t_load,
                y_load,
                evaluate_function=True,
                evaluate_n=len(t_load),
            )

            unload_results, _, _, unload_fit = exponential_decay.fit(
                t_unload,
                y_unload,
                evaluate_function=True,
                evaluate_n=len(t_unload),
            )

            fit = np.empty_like(trace, dtype=float)
            fit[:switch_idx] = load_fit
            fit[switch_idx:] = unload_fit

            return (
                fit,
                float(load_results["tau"]),
                float(unload_results["tau"]),
            )

        except Exception:
            logger.warning("Load/unload fit failed", exc_info=True)
            return np.full_like(trace, np.nan), np.nan, np.nan


LoadUnloadBench = make_benchmark_scan_exp(
    "LoadUnloadBench",
    LoadUnloadBenchFragment,
)
