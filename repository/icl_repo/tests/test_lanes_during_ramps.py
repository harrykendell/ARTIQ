import logging
from typing import *

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.experiment import *
from artiq.experiment import delay
from artiq.experiment import kernel
from artiq.experiment import now_mu
from ndscan.experiment import *
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import (
    make_set_beams_to_default,
)
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults
from icl_repo.lib.fragments.magnetic_fields import SetMagneticFieldsQuick
from icl_repo.lib.fragments.red_mot.red_mot_phases import NarrowRedCapturePhase


logger = logging.getLogger(__name__)

PHASE_DURATION = 100e-3


class NarrowRedCapturePhase100ms(NarrowRedCapturePhase):
    # Ensure that we have known duration and time_step for this test
    duration_default = PHASE_DURATION
    time_step_default = 100e-6


class TestRampLaneUse(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

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
            "test_phase",
            NarrowRedCapturePhase,
            chamber_2_field_setter=self.chamber_2_field_setter,
        )
        self.test_phase: NarrowRedCapturePhase

        self.test_phase.bind_suservo_setpoint_params_to_default_beam_setter(
            self.beam_setter
        )

        self.setattr_device("TTL_shutter_461_pushbeam")
        self.ttl_tester: TTLOut = self.TTL_shutter_461_pushbeam

    @kernel
    def run_once(self):
        logger.info("Precomputing handle")
        self.test_phase.precalculate_dma_handle()

        logger.info("Starting test phase")

        self.core.break_realtime()

        # This should cause an RTIO sequence error unless we're only using a single lane
        with parallel:
            with sequential:
                delay(PHASE_DURATION / 2)
                self.ttl_tester.pulse(1e-6)

            self.test_phase.do_phase()

        logger.info("Phase queuing completed")

        logger.info(
            "now_mu = %d, get_rtio_counter_mu = %d, diff=%fs",
            now_mu(),
            self.core.get_rtio_counter_mu(),
            self.core.mu_to_seconds(now_mu() - self.core.get_rtio_counter_mu()),
        )

        self.core.wait_until_mu(now_mu())

        logger.info("Phase output completed")


TestRampLaneUseExp = make_fragment_scan_exp(TestRampLaneUse)
