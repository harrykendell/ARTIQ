from copy import deepcopy

from artiq.experiment import delay
from artiq.experiment import kernel
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from utils.models import SUServoedBeam

from icl_repo.lib.constants import SUSERVOED_BEAMS
from icl_repo.lib.fragments.fluorescence_pulse import ImagingFluorescencePulse

MOT_BEAM_NO_SHUTTER = deepcopy(SUSERVOED_BEAMS["blue_3dmot_axialminus"])
MOT_BEAM_NO_SHUTTER.shutter_device = None
MOT_BEAM_WITH_SHUTTER = deepcopy(SUSERVOED_BEAMS["blue_3dmot_axialminus"])
IMAGING_BEAM = deepcopy(SUSERVOED_BEAMS["blue_imaging_switch"])


class _TestFluorescencePulse(ExpFragment):
    @kernel
    def run_once(self) -> None:
        self.core.break_realtime()
        for _ in range(10):
            delay(1.0)
            self.frag.do_imaging_pulse()


class FluorescencePulseMOTBeamWithoutShutter(_TestFluorescencePulse):
    def build_fragment(self) -> None:
        self.setattr_device("core")

        class _FluorPulse(ImagingFluorescencePulse):
            beam_infos = [MOT_BEAM_NO_SHUTTER]

        self.setattr_fragment(
            "frag",
            _FluorPulse,
        )
        self.frag: ImagingFluorescencePulse


class FluorescencePulseMOTBeamWithShutter(_TestFluorescencePulse):
    def build_fragment(self) -> None:
        self.setattr_device("core")

        class _FluorPulse(ImagingFluorescencePulse):
            beam_infos = [MOT_BEAM_WITH_SHUTTER]

        self.setattr_fragment(
            "frag",
            _FluorPulse,
        )


class FluorescencePulseMOTBeamAndImagingWithShutter(_TestFluorescencePulse):
    def build_fragment(self) -> None:
        self.setattr_device("core")

        class _FluorPulse(ImagingFluorescencePulse):
            beam_infos = [IMAGING_BEAM, MOT_BEAM_WITH_SHUTTER]

        self.setattr_fragment(
            "frag",
            _FluorPulse,
        )
        self.frag: ImagingFluorescencePulse


FluorescencePulseMOTBeamWithoutShutter = make_fragment_scan_exp(
    FluorescencePulseMOTBeamWithoutShutter
)
FluorescencePulseMOTBeamWithShutter = make_fragment_scan_exp(
    FluorescencePulseMOTBeamWithShutter
)
FluorescencePulseMOTBeamAndImagingWithShutter = make_fragment_scan_exp(
    FluorescencePulseMOTBeamAndImagingWithShutter
)
