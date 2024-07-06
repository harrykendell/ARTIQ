from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import parallel
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from icl_repo.lib.fragments.blue_3d_mot import Blue3DMOTFrag
from icl_repo.lib.fragments.cameras.dual_camera_measurer import DualCameraMeasurement
from icl_repo.lib.fragments.fluorescence_pulse import ImagingFluorescencePulse


class ImageBlueMOT(ExpFragment):
    def build_fragment(self) -> None:
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("blue_mot", Blue3DMOTFrag)
        self.blue_mot: Blue3DMOTFrag

        self.setattr_fragment(
            "dual_cameras", DualCameraMeasurement, hardware_trigger=True
        )
        self.dual_cameras: DualCameraMeasurement

        self.fluorescence_pulse: ImagingFluorescencePulse = self.setattr_fragment(
            "fluorescence_pulse", ImagingFluorescencePulse
        )

        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time of blue MOT",
            default=10e-3,
            unit="ms",
        )
        self.expansion_time: FloatParamHandle

        # Expose some important parameters
        self.setattr_param_rebind(
            "fluorescence_pulse_duration",
            self.fluorescence_pulse,
        )
        self.setattr_param_rebind("exposure_horiz", self.dual_cameras)
        self.setattr_param_rebind("exposure_vert", self.dual_cameras)

    @kernel
    def run_once(self) -> None:
        self.core.break_realtime()
        self.blue_mot.load_mot(clearout=False)

        delay(1.0)

        self.blue_mot.turn_off_3d_and_2d_beams()

        delay(self.expansion_time.get())

        with parallel:
            self.fluorescence_pulse.do_imaging_pulse()
            self.dual_cameras.trigger()

        self.core.wait_until_mu(now_mu())

        self.dual_cameras.save_data()


ImageBlueMOTExp = make_fragment_scan_exp(ImageBlueMOT)
