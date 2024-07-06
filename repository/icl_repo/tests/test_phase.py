"""
Test a simple phase
"""
import logging

from artiq.coredevice.core import Core
from artiq.experiment import *
from artiq.experiment import delay
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import TFloat
from ndscan.experiment import *

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import (
    make_set_beams_to_default,
)
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults
from icl_repo.lib.fragments.ramping_phase import GeneralRampingPhase

logger = logging.getLogger(__name__)


class TestPhaseDown(GeneralRampingPhase):
    suservos = [
        "suservo_aom_singlepass_689_red_mot_diagonal",
    ]

    default_suservo_nominal_setpoints = [1.0]
    default_suservo_setpoint_multiples_start = [1.0]
    default_suservo_setpoint_multiples_end = [0.1]

    duration_default = 100e-3
    time_step_default = 10e-3


class TestPhaseUp(GeneralRampingPhase):
    suservos = [
        "suservo_aom_singlepass_689_red_mot_diagonal",
    ]

    default_suservo_nominal_setpoints = [1.0]
    default_suservo_setpoint_multiples_start = [0.1]
    default_suservo_setpoint_multiples_end = [1.0]

    duration_default = 100e-3
    time_step_default = 10e-3

    add_final_point = True


class ExpFragWithPhaseFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment(
            "test_phase_down",
            TestPhaseDown,
        )
        self.test_phase_down: GeneralRampingPhase

        self.setattr_fragment(
            "test_phase_up",
            TestPhaseUp,
        )
        self.test_phase_up: GeneralRampingPhase

        self.setattr_fragment(
            "diagonal_beam_setter",
            make_set_beams_to_default(
                [constants.SUSERVOED_BEAMS["red_mot_diagonal"]],
                name="DiagonalBeamSettings",
            ),
        )
        self.diagonal_beam_setter: SetBeamsToDefaults

        self.setattr_param(
            "delay_between_phases",
            FloatParam,
            description="Delay before starting DMA playback",
            default=600e-6,
            unit="us",
            min=0.0,
        )

        self.setattr_param(
            "num_repeats",
            IntParam,
            description="Number of times to repeat phase",
            default=10,
            min=1,
        )

    @kernel
    def run_once(self):
        logger.info("Precomputing handles")
        self.test_phase_down.precalculate_dma_handle()
        self.test_phase_up.precalculate_dma_handle()

        logger.info("Enabling diagonal beam")
        self.core.break_realtime()
        self.diagonal_beam_setter.turn_on_all()

        logger.info("Starting test phases")
        self.core.break_realtime()

        for _ in range(self.num_repeats.get()):
            delay(self.delay_between_phases.get())
            self.test_phase_down.do_phase()
            self.test_phase_up.do_phase()

        logger.info("Phase queuing completed")

        logger.info(
            "now_mu = %d, get_rtio_counter_mu = %d, diff=%fs",
            now_mu(),
            self.core.get_rtio_counter_mu(),
            self.core.mu_to_seconds(now_mu() - self.core.get_rtio_counter_mu()),
        )

        self.core.wait_until_mu(now_mu())

        logger.info("Phase output completed")


ExpFragWithPhase = make_fragment_scan_exp(ExpFragWithPhaseFrag)
