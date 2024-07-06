import logging

from artiq.experiment import delay
from artiq.experiment import kernel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from utils.suservo import LibSetSUServoStatic

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults
from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import SpectroscopyMixin
from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import TripleImageMOTFrag


logger = logging.getLogger(__name__)


class SpectroscopyWithKinetics_MOTBeam(TripleImageMOTFrag, SpectroscopyMixin):
    """
    689nm spectroscopy MOTBEAM

    689nm spectroscopy with fast kinetics imaging using the red MOT beam
    """

    def pre_build_fragment_hook(self):
        self.setattr_fragment(
            "red_axial_minus",
            LibSetSUServoStatic,
            "suservo_aom_singlepass_689_red_mot_sigmaminus",
        )
        self.red_axial_minus: LibSetSUServoStatic

    @kernel
    def pre_expansion_hook(self):
        self.red_mot.red_beam_controller.set_mot_detuning(
            self.spectroscopy_pulse_aom_detuning.get()
        )

        self.red_axial_minus.suservo_channel.set_y(
            profile=self.red_axial_minus.suservo_profile,
            y=self.spectroscopy_pulse_aom_amplitude.get(),
        )

    @kernel
    def do_spectroscopy_hook(self):
        self.red_axial_minus.set_channel_state(rf_switch_state=True, enable_iir=False)
        delay(self.spectroscopy_pulse_time.get())
        self.red_axial_minus.set_channel_state(rf_switch_state=False, enable_iir=False)


class SpectroscopyWithKinetics_UpBeam(TripleImageMOTFrag, SpectroscopyMixin):
    """
    689nm spectroscopy UP

    689nm spectroscopy with fast kinetics imaging using the red up beam
    """

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

    @kernel
    def do_spectroscopy_hook(self):
        self.up_beam_suservo.set_channel_state(rf_switch_state=True, enable_iir=False)
        delay(self.spectroscopy_pulse_time.get())
        self.up_beam_suservo.set_channel_state(rf_switch_state=False, enable_iir=False)


SpectroscopyWithKineticsMOTExp = make_fragment_scan_exp(
    SpectroscopyWithKinetics_MOTBeam
)
SpectroscopyWithKineticyUpExp = make_fragment_scan_exp(SpectroscopyWithKinetics_UpBeam)
