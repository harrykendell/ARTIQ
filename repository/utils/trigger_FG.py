# This code is written to add the external trigger to the Keysight Function Generator.
# It simulatenously unlocks the 852nm laser by turning off the servo while the FG is triggered.

# Author : Yolan Ankaine
# Date : Jan 2026

import logging
import numpy as np

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.language import delay, kernel, rpc, ms, us, Hz, parallel, TFloat, sequential
from ndscan.experiment import BoolParam, ExpFragment, FloatParam
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from ndscan.experiment.entry_point import make_fragment_scan_exp
from controllers.ms024 import MSO24
from controllers.Agilent33600A import Agilent33600A
from controllers.RedPitaya import RedPitaya

logger = logging.getLogger(__name__)

import json
from pathlib import Path

import pandas as pd
from scipy.signal import savgol_filter


# -------- Main experiment fragment --------- #
class TriggerFuncGenFrag(ExpFragment):
    """
    Trigger a function generator via TTL

    we need the scope connected on 192.168.0.5 and the AFG on 192.168.0.7
    """

    def build_fragment(self):
        # Devices
        self.setattr_device("core")
        self.core: Core

        # Define TTL channels
        self.unlock_ttl: TTLInOut = self.get_device("852_unlock")
        self.AFG_ext_trigger: TTLInOut = self.get_device("AFG_ext_trigger")
        self.scope_ttl: TTLInOut = self.get_device("scope_trigger")
        self.RP_ext_trigger: TTLInOut = self.get_device("RedPitaya_trigger")

        # UI parameter : laser settling time
        self.setattr_param(
            "time_to_shift",
            FloatParam,
            "Delay for the laser to move",
            default=500 * ms,
            unit="ms",
        )
        self.time_to_shift: FloatParamHandle

        # UI parameter : modulation frequency
        self.setattr_param(
            "frequency",
            FloatParam,
            "Modulation Frequency",
            default=100 * Hz,
            unit="Hz",
        )
        self.frequency: FloatParamHandle

        self.voltage: FloatParamHandle = self.setattr_param(
            "voltage",
            FloatParam,
            "Modulation Voltage (Max voltage)",
            default=4.0,
            unit="V",
        )

        self.setattr_param("use_redpitaya", BoolParam, "Use Red Pitaya", default=False)
        self.use_redpitaya: BoolParamHandle

    @rpc
    def setup_scope(self, timebase) -> TFloat:
        with MSO24(silent=True) as ms024:
            ms024.cancel_acquisition()
            ms024.set_trigger(channel=4, level=1.0)
            ms024.set_timebase(timebase)
            ms024.start_acquisition()
            return ms024.wait_for_ready()

    @rpc
    def choose_timebase(self, freq) -> TFloat:
        """
        We need to fit 15 periods inside 8 timebases at maximum

        Timebases can only be 1,2,4 * 10^n seconds, so we need to find the smallest timebase that can fit 15 periods in 8 timebases
        """
        time_for_15_periods = 15.0 / freq
        max_timebase = time_for_15_periods / 8.0

        # Find our power and multiplier
        power = int(np.floor(np.log10(max_timebase)))
        multiplier = max_timebase / (10**power)

        if multiplier <= 1:
            chosen_multiplier = 1
        elif multiplier <= 2:
            chosen_multiplier = 2
        elif multiplier <= 4:
            chosen_multiplier = 4
        else:
            chosen_multiplier = 10
        chosen_timebase = chosen_multiplier * (10**power)
        return chosen_timebase

    @rpc(flags={"async"})
    def acquire(self, freq):
        dev = "Red Pitaya" if self.use_redpitaya.get() else "AFG"
        filename = f"{freq}Hz_SINE_{dev}"
        with MSO24(silent=True) as ms024:
            ts, vs = ms024.get_trace([2, 3, 4], already_acquiring=True)
        ms024.save_traces_to_file(ts, vs, filename=filename)

    @rpc
    def setup_afg(self, freq):
        with Agilent33600A(silent=True) as afg:
            afg.sin_pulse(1, freq, self.voltage.get(), 15)

    @rpc
    def setup_redpitaya(self, freq):
        path = Path(
            "~/Desktop/redpitaya/RedPitayaFixed_measurements/fit_details.json"
        ).expanduser()
        table, points = load_transfer_table(path, normalize_to_dc=True)

        freq_points = table["freq_hz"].to_numpy(float)
        gain_points = table["gain"].to_numpy(float)
        phase_points = np.pi * table["phase_pi"].to_numpy(float)  # convert to radians
        gain_smooth, phase_smooth = smooth_curves(
            freq_points, gain_points, phase_points
        )

        MAX_V = 5.0  # what can the amp put out
        A_MIN = np.min(gain_points)
        A_MAX = np.max(gain_points)
        max_always_available = (
            MAX_V * A_MIN / A_MAX
        )  # what can we compensate up to without trying to overdrive at some freqs
        if self.voltage.get() > MAX_V:  # max_always_available
            logger.warning(
                f"Requested voltage {self.voltage.get():.2f}V exceeds the maximum compensatable voltage {max_always_available:.2f}V. Output may be distorted."
            )
        # compute voltage amplitude and phase for the requested frequency
        DRIVE_V = self.voltage.get() * A_MIN / gain_smooth(self.frequency.get())
        DRIVE_PHASE = (
            phase_smooth(self.frequency.get()) * 360.0 / (2 * np.pi)
        )  # in degrees

        with RedPitaya() as rp:
            rp.sin_burst(  # compensated drive on channel 1
                chan=1,
                freq=freq,
                voltage=DRIVE_V,
                num_cycles=15,
                phase=DRIVE_PHASE,
                usingAMP=True,
            )
            rp.sin_burst(
                chan=2,  # uncompensated drive on channel 2
                freq=freq,
                voltage=self.voltage.get(),
                num_cycles=15,
                phase=0.0,
                usingAMP=True,
            )

    @kernel
    def run_once(self):
        """
        The experimental procedure is:

        1. Unlock 852, allow time to unlock
        2. Trigger AFG+Scope via TTL
        3. Run sine wave through AFG for 20 periods
        4. TTLs go low and Relock 852 after delay
        """
        self.core.reset()  # Ensure clean state

        timebase = self.choose_timebase(self.frequency.get())
        self.setup_scope(timebase)

        if self.use_redpitaya.get():
            self.setup_redpitaya(self.frequency.get())
        else:
            self.setup_afg(self.frequency.get())

        # Reset the core  and break realtime to ensure clean timing boundary
        self.core.break_realtime()

        # ----- Experiment sequence -----#
        # 1. Unlock 852, allow time to unlock
        self.unlock_ttl.on()
        delay(self.time_to_shift.get())

        # 2. + 3. Trigger AFG+Scope via TTL
        with parallel:
            self.AFG_ext_trigger.on()  # ensure ttl is output
            self.RP_ext_trigger.on()  # trigger RP if used
            self.scope_ttl.on()  # trigger scope

        # 4. TTLs go low and relock 852 after delay
        # delay for 15 pulses at the given freq
        # We dont want the RP and AFG to mistake the falling edge as a new trigger
        todelay = 15.0 / self.frequency.get()
        delay(todelay)
        self.scope_ttl.off()
        self.unlock_ttl.off()

        # The RP seems to retrigger on the falling edge so keep this outside of data collection time
        delay(todelay)
        self.AFG_ext_trigger.off()
        self.RP_ext_trigger.off()

        self.acquire(self.frequency.get())


TriggerFuncGen = make_fragment_scan_exp(TriggerFuncGenFrag)

# To generate the frequencies for the scan, we can use the following code in a notebook:
"""
import numpy as np

freqs = np.logspace(np.log10(10), np.log10(0.5e6), num=100)
print(f"{', '.join([f'{f:.2e}' for f in freqs])}")
"""


# Functions to load and process the transfer function points from the fit details JSON file
def load_transfer_points(fit_details_path):
    """
    Load transfer function points from a single JSON file containing fit details.
    """
    payload = json.loads(Path(fit_details_path).read_text(encoding="utf-8"))
    param_index = {
        p.get("key"): i
        for i, p in enumerate(payload.get("parameters", []))
        if isinstance(p, dict) and p.get("key")
    }

    rows = []
    for entry in payload.get("batch_results", []):
        fit_results = entry.get("fit_results")
        params = fit_results.get("params")

        # H values
        freq = float(entry.get("captures").get("freq"))
        gain = float(params[param_index["A_mod"]])
        phase_pi = float(params[param_index["phi_delta"]])

        # time lag diagnostics - NB this needs careful consideration as it probably conflates with the phase lag?
        ch = fit_results.get("channel_results")
        ch3_b1 = float(ch.get("CH3").get("boundaries")[0])
        ch4_b1 = float(ch.get("CH4").get("boundaries")[0])
        delay_s = ch4_b1 - ch3_b1
        rows.append((freq, gain, phase_pi, ch3_b1, ch4_b1, delay_s))

    points = pd.DataFrame(
        rows,
        columns=[
            "freq_hz",
            "gain",
            "phase_pi",
            "ch3_boundary_1_s",
            "ch4_boundary_1_s",
            "boundary_delay_s",
        ],
    )
    if points.empty:
        raise ValueError(f"No valid fit points found in {fit_details_path}")
    return points.sort_values("freq_hz", ignore_index=True)


def load_transfer_table(
    fit_details_path, *, normalize_to_dc=True, aggregation_method="median"
):
    """
    Generate a transfer function calibration table from a JSON file containing fit details
        Optionally normalize gain to the DC (lowest frequency) reference.
        Remove duplicate frequency points by using some average (default is median) of their gain and phase values.
    """
    points = load_transfer_points(fit_details_path)
    # If we have duplicates take the median
    table = (
        points.groupby("freq_hz", as_index=False)
        .agg(
            gain=("gain", aggregation_method), phase_pi=("phase_pi", aggregation_method)
        )
        .sort_values("freq_hz", ignore_index=True)
    )

    if normalize_to_dc:
        dc_gain = float(table["gain"].iloc[0])
        if (not np.isfinite(dc_gain)) or dc_gain <= 0:
            raise ValueError("Cannot normalize gain with non-positive DC reference")
        table["gain"] = table["gain"] / dc_gain
        points = points.copy()
        points["gain"] = points["gain"] / dc_gain
    return table, points


def smooth(gain, phase, window_length=9, polyorder=2):
    gain_smooth = savgol_filter(gain, window_length=window_length, polyorder=polyorder)
    phase_smooth = savgol_filter(
        phase, window_length=window_length, polyorder=polyorder
    )
    return gain_smooth, phase_smooth


def smooth_curves(
    freq_hz,
    gain,
    phase,
    window_length: int = 15,
    polyorder: int = 2,
):
    """
    Smooth gain and phase curves and return callables on arbitrary frequency.
    Outside the provided range:
      - gain -> 1
      - phase -> 0
    """
    freq_hz = np.asarray(freq_hz, dtype=float)
    x = np.log10(freq_hz)

    gain_smooth, phase_smooth = smooth(
        gain, phase, window_length=window_length, polyorder=polyorder
    )

    def gain_fn(f):
        f = np.asarray(f, dtype=float)
        xf = np.log10(f)
        y = np.interp(xf, x, gain_smooth, left=1.0, right=1.0)
        return float(y) if np.ndim(f) == 0 else y

    def phase_fn(f):
        f = np.asarray(f, dtype=float)
        xf = np.log10(f)
        y = np.interp(xf, x, phase_smooth, left=0.0, right=0.0)
        return float(y) if np.ndim(f) == 0 else y

    return gain_fn, phase_fn


### Notes on computing the drive voltage
## A_mod max and min values
# A_MAX = 1.7
# A_MIN = 0.5

# # maximum voltage from amplifier
# V = 5

# # based on attenuation whats the best voltage we can see at the most attenuating frequency, if at the least attenuating we are getting 5V
# max_always_available = V * A_MIN / A_MAX

# A_f = 1.7
# V_target = 1.47

# set = V * A_MIN / A_f

# print(f"Set voltage: {set:.2f} V vs max possible {max_always_available:.2f} V")
