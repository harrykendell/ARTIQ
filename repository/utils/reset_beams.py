from artiq.coredevice.core import Core
from artiq.experiment import kernel
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from repository.fragments.default_beam_setter import (
    SetBeamsToDefaults,
    make_set_beams_to_default,
)
from repository.models.devices import SUServoedBeam


class ResetSUServoFrag(ExpFragment):
    """
    Reset all beams to default settings
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        # Get beam setter fragment
        self.setattr_fragment(
            "beam_default_setter",
            make_set_beams_to_default(
                SUServoedBeam.all(),
                name="BeamSettings",
            ),
        )
        self.beam_default_setter: SetBeamsToDefaults

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()

    @kernel
    def run_once(self):
        self.core.break_realtime()

        self.beam_default_setter.turn_on_all(light_enabled=True)


ResetSUServo = make_fragment_scan_exp(ResetSUServoFrag)
