import logging
from typing import *

from artiq.experiment import *
from artiq.experiment import delay
from ndscan.experiment import *

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import (
    make_set_beams_to_default,
)
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults
from icl_repo.lib.fragments.magnetic_fields import SetMagneticFieldsQuick
from icl_repo.lib.fragments.red_mot.red_mot_phases import BroadbandRedPhase
from icl_repo.lib.fragments.red_mot.red_mot_phases import NarrowRedCapturePhase
from icl_repo.lib.fragments.red_mot.red_mot_phases import NarrowRedCompressionPhase
from icl_repo.lib.fragments.red_mot.red_mot_phases import (
    RedRampingPhaseWithFieldsAndSUServoBindings,
)

logger = logging.getLogger(__name__)


class TestRedPhasesExp(ExpFragment):
    def build_fragment(self) -> None:
        self.setattr_device("core")

        self.setattr_fragment(
            "beam_setter",
            make_set_beams_to_default(
                [
                    constants.SUSERVOED_BEAMS["red_mot_diagonal"],
                    constants.SUSERVOED_BEAMS["red_mot_sigmaplus"],
                    constants.SUSERVOED_BEAMS["red_mot_sigmaminus"],
                    constants.SUSERVOED_BEAMS["red_up"],
                ],
                name="beam_setter",
            ),
        )
        self.beam_setter: SetBeamsToDefaults

        self.setattr_fragment(
            "chamber_2_field_setter",
            SetMagneticFieldsQuick,
        )
        self.chamber_2_field_setter: SetMagneticFieldsQuick

        self.setattr_fragment(
            "frag0",
            BroadbandRedPhase,
            chamber_2_field_setter=self.chamber_2_field_setter,
        )
        self.frag0: RedRampingPhaseWithFieldsAndSUServoBindings

        self.setattr_fragment(
            "frag1",
            NarrowRedCapturePhase,
            chamber_2_field_setter=self.chamber_2_field_setter,
        )
        self.frag1: RedRampingPhaseWithFieldsAndSUServoBindings

        self.setattr_fragment(
            "frag2",
            NarrowRedCompressionPhase,
            chamber_2_field_setter=self.chamber_2_field_setter,
        )
        self.frag2: RedRampingPhaseWithFieldsAndSUServoBindings

        self.frag0.bind_suservo_setpoint_params_to_default_beam_setter(self.beam_setter)
        self.frag1.bind_suservo_setpoint_params_to_default_beam_setter(self.beam_setter)
        self.frag2.bind_suservo_setpoint_params_to_default_beam_setter(self.beam_setter)

    @kernel
    def run_once(self) -> None:
        self.frag0.precalculate_dma_handle()
        self.frag1.precalculate_dma_handle()
        self.frag2.precalculate_dma_handle()

        self.core.break_realtime()
        delay(100e-3)
        self.beam_setter.turn_on_all(light_enabled=True)
        delay(150e-3)

        self.core.break_realtime()
        self.frag0.do_phase()
        self.frag1.do_phase()
        self.frag2.do_phase()

        logger.info("Ramps completed")


TestRedPhases = make_fragment_scan_exp(TestRedPhasesExp)
