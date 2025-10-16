import logging

from artiq.coredevice.core import Core
from artiq.language import delay, kernel
from artiq.language.units import ms, s, V
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from repository.fragments.ramp import Ramp, default
from repository.models.devices import Eom, SUServoedBeam, VDrivenSupply  # noqa: F401
from repository.fragments.mot import MOT


from ndscan.experiment.default_analysis import DefaultAnalysis
from ndscan.experiment.default_analysis import CustomAnalysis
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle, ParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera
from repository.imaging.processor import AbsImage  # noqa: E402
from repository.models.devices import SUServoedBeam
from repository.models.device_db import 


logger = logging.getLogger(__name__)


class RAMP(ExpFragment):
    """
    CHECK ODT RAMPING WORKS FINE
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

    @kernel
    def run_once(self):
        self.ramp1.precalculate_dma_handle()

        self.core.break_realtime()
        delay(1 * s)
        
        self.ramp1.do()
        delay(1 * s)

        logger.warning("Ramps completed")

RAMP = make_fragment_scan_exp(RAMP)