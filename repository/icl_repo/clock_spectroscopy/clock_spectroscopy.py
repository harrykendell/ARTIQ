import abc
import logging

from artiq.experiment import at_mu
from artiq.experiment import delay
from artiq.experiment import delay_mu
from artiq.experiment import kernel
from artiq.experiment import now_mu
from ndscan.experiment import FloatChannel
from ndscan.experiment import OnlineFit
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle
from numpy import int64
from utils.suservo import LibSetSUServoStatic
from utils.models import SUServoedBeam

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults
from icl_repo.lib.fragments.cameras.andor_camera import AndorCameraControl
from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import (
    RedMOTWithExperiment,
)
from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import SpectroscopyMixin
from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import TripleImageMOTFrag


logger = logging.getLogger(__name__)

CLOCK_BEAM_INFO: SUServoedBeam = constants.SUSERVOED_BEAMS["clock_up"]


class BasicClockSpectroscopyFrag(SpectroscopyMixin, TripleImageMOTFrag):
    """
    Basic clock spectroscopy

    Use the up clock beam for spectroscopy, altering the (single-pass) AOM

    Image the ground state atoms, repump and image the excited state, then image
    once more for background
    """

    def build_fragment(self):
        super().build_fragment()

        self.setattr_param(
            "delay_repumps_after_first_pulse",
            FloatParam,
            "Delay after first fluorescence pulse before repumps turn on",
            default=1e-3,
            unit="ms",
        )
        self.delay_repumps_after_first_pulse: FloatParamHandle

    def pre_build_fragment_hook(self):
        self.setattr_fragment(
            "clock_up",
            LibSetSUServoStatic,
            "suservo_aom_698_up_switch",
        )
        self.clock_up: LibSetSUServoStatic

    @kernel
    def before_start_hook(self):
        self.core.break_realtime()
        self.clock_up.set_suservo(
            freq=CLOCK_BEAM_INFO.frequency + self.spectroscopy_pulse_aom_detuning.get(),
            amplitude=self.spectroscopy_pulse_aom_amplitude.get(),
            attenuation=CLOCK_BEAM_INFO.attenuation,
            rf_switch_state=False,
            enable_iir=False,
        )

    @kernel
    def do_spectroscopy_hook(self):
        self.clock_up.set_channel_state(rf_switch_state=True, enable_iir=False)
        delay(self.spectroscopy_pulse_time.get())
        self.clock_up.set_channel_state(rf_switch_state=False, enable_iir=False)

    @kernel
    def do_first_pulse(self, andor_exposure):
        self._do_pulse(andor_exposure)
        delay(self.delay_repumps_after_first_pulse.get())
        self.blue_3d_mot.turn_on_repumpers()


BasicClockSpectroscopy = make_fragment_scan_exp(BasicClockSpectroscopyFrag)
