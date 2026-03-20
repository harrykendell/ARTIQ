# This code is written to add the external trigger to the Keysight Function Generator.
# It simulatenously unlocks the 852nm laser by turning off the servo while the FG is triggered.

# Author : Yolan Ankaine
# Date : Jan 2026

import logging
import numpy as np

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.language import delay, kernel, rpc, ms, s, Hz, parallel, TFloat
from ndscan.experiment import BoolParam, ExpFragment, FloatParam
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from ndscan.experiment.entry_point import make_fragment_scan_exp
from controllers.ms024 import MSO24
from controllers.Agilent33600A import Agilent33600A
from controllers.RedPitaya import RedPitaya

logger = logging.getLogger(__name__)


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
            ms024.set_trigger(channel= 4, level=1.0)
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
        multiplier = max_timebase / (10 ** power)

        if multiplier <= 1:
            chosen_multiplier = 1
        elif multiplier <= 2:
            chosen_multiplier = 2
        elif multiplier <= 4:
            chosen_multiplier = 4
        else:
            chosen_multiplier = 10
        chosen_timebase = chosen_multiplier * (10 ** power)
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
        with RedPitaya() as rp:
            rp.sin_burst(chan=1, freq=freq, voltage=self.voltage.get(), num_cycles=15, usingAMP=True)

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
        todelay = 15.0 / self.frequency.get()
        delay(todelay)
        self.AFG_ext_trigger.off()
        self.RP_ext_trigger.off()
        self.scope_ttl.off()
        self.unlock_ttl.off()

        delay(0.2 * s)
        self.acquire(self.frequency.get())


TriggerFuncGen = make_fragment_scan_exp(TriggerFuncGenFrag)


# To generate the frequencies for the scan, we can use the following code in a notebook:
# freqs = np.logspace(1, 6, 100, endpoint=True)
# print(f"{', '.join([f'{f:.2e}' for f in freqs])}")