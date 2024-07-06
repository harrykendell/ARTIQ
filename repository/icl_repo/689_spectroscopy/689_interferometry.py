import logging

from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.experiment import delay
from artiq.experiment import kernel
from ndscan.experiment import OnlineFit
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle
from utils.suservo import LibSetSUServoStatic

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import (
    make_set_beams_to_default,
)
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults

logger = logging.getLogger(__name__)

from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import (
    TripleImageMOTFrag,
    SpectroscopyMixin,
)


class _InterferometryCommon(TripleImageMOTFrag, SpectroscopyMixin):
    def pre_build_fragment_hook(self):
        class _UpBeamSetter(SetBeamsToDefaults):
            default_suservo_beam_infos = [constants.SUSERVOED_BEAMS["red_up"]]

        self.setattr_fragment("up_beam_default_setter", _UpBeamSetter)
        self.up_beam_default_setter: SetBeamsToDefaults

        self.setattr_fragment(
            "up_beam_suservo",
            LibSetSUServoStatic,
            constants.SUSERVOED_BEAMS["red_up"].suservo_device,
        )
        self.up_beam_suservo: LibSetSUServoStatic

    def build_fragment(self):
        super().build_fragment()

        self.setattr_param(
            "delay_between_interferometry_pulses",
            FloatParam,
            "Delay between interferometry pulses",
            default=100e-9,
            unit="us",
        )
        self.delay_between_interferometry_pulses: FloatParamHandle

        self.setattr_param(
            "phase_step",
            FloatParam,
            "Phase step in interferometry sequence",
            default=0.0,
        )
        self.phase_step: FloatParamHandle

    @kernel
    def before_start_hook(self):
        # Enable the Up beam with default settings, but turn off the AOM and open the shutter
        self.core.break_realtime()
        self.up_beam_default_setter.turn_on_all(light_enabled=True)
        self.up_beam_suservo.set_channel_state(rf_switch_state=False, enable_iir=False)
        self.up_beam_suservo.suservo_channel.set_y(
            profile=self.up_beam_suservo.suservo_profile,
            y=self.spectroscopy_pulse_aom_amplitude.get(),
        )

    def get_default_analyses(self):
        super_analysis = super().get_default_analyses()

        return super_analysis + [
            OnlineFit(
                "sinusoid",
                data={
                    "x": self.phase_step,
                    "y": self.excitation_fraction,
                },
                constants={
                    "t_dead": -100.0,
                },
            )
        ]


class UpBeamInterferometryIJD(_InterferometryCommon):
    """
    Up beam interferometry - IJD phase shift
    """

    def host_setup(self):
        super().host_setup()

        self.setattr_device("urukul9910_aom_doublepass_689_red_injection")
        self.urukul9910_aom_doublepass_689_red_injection: AD9910

    @kernel
    def do_spectroscopy_hook(self):
        t_pi_pulse = self.spectroscopy_pulse_time.get()

        # Allow negative phases up to -10
        phase_constant = 10.0

        # A bit fragile, but recalculate the injection AOM's frequency here
        freq = (
            constants.RED_INJECTION_AOM_FREQUENCY
            + self.red_mot.red_beam_controller.injection_aom_static_frequency.get()
            + self.spectroscopy_pulse_aom_detuning.get()
        )

        # Set initial phase
        self.urukul9910_aom_doublepass_689_red_injection.set(
            frequency=freq, phase=phase_constant
        )

        delay(self.delay_between_interferometry_pulses.get())

        # PI/2 PULSE
        self.up_beam_suservo.set_channel_state(rf_switch_state=True, enable_iir=False)
        delay(t_pi_pulse / 2)
        self.up_beam_suservo.set_channel_state(rf_switch_state=False, enable_iir=False)

        # Phase step
        self.urukul9910_aom_doublepass_689_red_injection.set(
            frequency=freq,
            phase=0.5 * self.phase_step.get() + phase_constant,
        )

        delay(self.delay_between_interferometry_pulses.get())

        # PI PULSE
        self.up_beam_suservo.set_channel_state(rf_switch_state=True, enable_iir=False)
        delay(t_pi_pulse)
        self.up_beam_suservo.set_channel_state(rf_switch_state=False, enable_iir=False)

        # Phase step again
        self.urukul9910_aom_doublepass_689_red_injection.set(
            frequency=freq,
            phase=2.0 * self.phase_step.get() + phase_constant,
        )

        delay(self.delay_between_interferometry_pulses.get())

        # PI/2 PULSE
        self.up_beam_suservo.set_channel_state(rf_switch_state=True, enable_iir=False)
        delay(t_pi_pulse / 2)
        self.up_beam_suservo.set_channel_state(rf_switch_state=False, enable_iir=False)


class UpBeamInterferometrySUServo(_InterferometryCommon):
    """
    Up beam interferometry - delivery phase shift
    """

    def host_setup(self):
        super().host_setup()

        self.setattr_device("suservo_aom_singlepass_689_up")
        self.suservo_aom_singlepass_689_up: SUServoChannel

        # Kernel vars
        self.suservo_freq = constants.SUSERVOED_BEAMS["red_up"].frequency
        # Allow negative phases up to -10
        self.phase_constant = 10.0

    @kernel
    def before_start_hook(self):
        # Enable the Up beam with default settings, but turn off the AOM and open the shutter
        self.core.break_realtime()
        self.up_beam_default_setter.turn_on_all(light_enabled=True)

        # Set up SUServo profiles manually with config options for different phases
        self.suservo_aom_singlepass_689_up.set_dds(
            0, frequency=self.suservo_freq, offset=0.0, phase=self.phase_constant
        )
        self.suservo_aom_singlepass_689_up.set_dds(
            1,
            frequency=self.suservo_freq,
            offset=0.0,
            phase=self.phase_constant + 1.0 * self.phase_step.get(),
        )
        self.suservo_aom_singlepass_689_up.set_dds(
            2,
            frequency=self.suservo_freq,
            offset=0.0,
            phase=self.phase_constant + 4.0 * self.phase_step.get(),
        )

        for i in range(3):
            self.suservo_aom_singlepass_689_up.set_y(
                profile=i,
                y=self.spectroscopy_pulse_aom_amplitude.get(),
            )

        # Start on profile 0 with AOM off
        self.suservo_aom_singlepass_689_up.set(en_out=0, en_iir=0, profile=0)

    @kernel
    def do_spectroscopy_hook(self):
        t_pi_pulse = self.spectroscopy_pulse_time.get()

        # Ensure we're on profile 0
        self.suservo_aom_singlepass_689_up.set(en_out=0, en_iir=0, profile=0)

        delay(self.delay_between_interferometry_pulses.get())

        # PI/2 PULSE
        self.suservo_aom_singlepass_689_up.set(en_out=1, en_iir=0, profile=0)
        delay(t_pi_pulse / 2)
        # Phase step & turn off
        self.suservo_aom_singlepass_689_up.set(en_out=0, en_iir=0, profile=1)

        delay(self.delay_between_interferometry_pulses.get())

        # PI PULSE
        self.suservo_aom_singlepass_689_up.set(en_out=1, en_iir=0, profile=1)
        delay(t_pi_pulse)
        # Phase step and turn off
        self.suservo_aom_singlepass_689_up.set(en_out=0, en_iir=0, profile=2)

        delay(self.delay_between_interferometry_pulses.get())

        # PI/2 PULSE
        self.suservo_aom_singlepass_689_up.set(en_out=1, en_iir=0, profile=2)
        delay(t_pi_pulse / 2)
        self.suservo_aom_singlepass_689_up.set(en_out=0, en_iir=0, profile=0)


UpBeamInterferometryIJDExp = make_fragment_scan_exp(UpBeamInterferometryIJD)
UpBeamInterferometrySUServoExp = make_fragment_scan_exp(UpBeamInterferometrySUServo)
