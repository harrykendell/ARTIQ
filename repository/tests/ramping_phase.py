import logging

from artiq.coredevice.core import Core
from artiq.language import delay, kernel
from artiq.language.units import ms, s
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from repository.fragments.ramp import Ramp, default
from repository.models.devices import Eom, SUServoedBeam, VDrivenSupply  # noqa: F401

logger = logging.getLogger(__name__)


class RampPhase(ExpFragment):
    """
    Can we make Ramping phases work
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        class Ramp1(Ramp):
            duration_default = 10 * ms

            supplies = VDrivenSupply["X1", "X2", "Y"]
            supplies_end = [1.5, 0.0, default]

        self.ramp1: Ramp1 = self.setattr_fragment("ramp", Ramp1)

        class Ramp2(Ramp):
            duration_default = 10 * ms

            supplies = VDrivenSupply["X1", "X2", "Y"]
            supplies_start = [self.ramp1, default, 2.0]
            supplies_end = [default, self.ramp1, 1.0]

        self.ramp2: Ramp2 = self.setattr_fragment("ramp2", Ramp2)

    @kernel
    def run_once(self):
        self.ramp1.precalculate_dma_handle()
        self.ramp2.precalculate_dma_handle()

        self.core.break_realtime()
        delay(1 * s)
        self.ramp1.do()
        delay(1 * s)
        self.ramp2.do()

        logger.warning("Ramps completed")


RampPhase = make_fragment_scan_exp(RampPhase)
