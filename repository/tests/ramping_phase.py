from repository.models.devices import SUServoedBeam, Eom, VDrivenSupply
from repository.fragments.ramp import Ramp

from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from artiq.language.units import ms, s, MHz
from artiq.language import kernel, delay
from artiq.coredevice.core import Core
import logging

logger = logging.getLogger(__name__)


class RampPhase(ExpFragment):
    """
    Can we make Ramping phases work
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("ramp", CompressionRamp)
        self.ramp: CompressionRamp

    @kernel
    def run_once(self):
        self.ramp.precalculate_dma_handle()

        self.core.break_realtime()
        delay(1 * s)
        self.ramp.do()
        delay(1.0)

        logger.warning("Ramps completed")


RampPhase = make_fragment_scan_exp(RampPhase)


class CompressionRamp(Ramp):
    duration_default = 10 * ms

    suservos = [SUServoedBeam["CDT1"]]
    suservo_setpoint_end = [0.5 * SUServoedBeam["CDT1"].setpoint]
    suservo_detuning_end = [-10 * MHz]

    eoms = [Eom["repump"]]

    supplies = [VDrivenSupply["Z"]]
    supplies_start = [0.0]
    supplies_end = [1.0]
