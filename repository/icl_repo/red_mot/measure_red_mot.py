import logging

from artiq.coredevice.core import Core
from artiq.experiment import at_mu
from artiq.experiment import delay
from artiq.experiment import delay_mu
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import parallel
from artiq.experiment import sequential
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatChannel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from icl_repo.lib import constants
from icl_repo.lib.fragments.blue_3d_mot import Blue3DMOTFrag
from icl_repo.lib.fragments.cameras.andor_camera import AndorCameraControl
from icl_repo.lib.fragments.cameras.dual_camera_measurer import DualCameraMeasurement
from icl_repo.lib.fragments.fluorescence_pulse import ToggleableFluorescencePulse
from icl_repo.lib.fragments.red_mot import NarrowbandRedMOTFrag

logger = logging.getLogger(__name__)


class RedMOTBase(ExpFragment):
    def build_fragment(self) -> None:
        self.setattr_device("core")
        self.core: Core

        # %% Fragments

        self.setattr_fragment("blue_3d_mot", Blue3DMOTFrag)
        self.blue_3d_mot: Blue3DMOTFrag

        self.setattr_fragment("red_mot", NarrowbandRedMOTFrag)
        self.red_mot: NarrowbandRedMOTFrag

        self.setattr_fragment(
            "camera_interface", DualCameraMeasurement, hardware_trigger=True
        )
        self.camera_interface: DualCameraMeasurement

        self.setattr_fragment("fluorescence_pulse", ToggleableFluorescencePulse)
        self.fluorescence_pulse: ToggleableFluorescencePulse

        # %% Params

        # Expansion time - can be negative
        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Time to expand MOT for before imaging",
            default=0.0,
            unit="us",
        )
        self.expansion_time: FloatParamHandle

        # %% Rebound params

        self.setattr_param_rebind(
            "exposure_horiz",
            self.camera_interface,
            "exposure_horiz",
            default=constants.DEFAULT_CAMERA_EXPOSURE_TIME,
            description="Horizontal camera exposure time",
            unit="us",
        )
        self.setattr_param_rebind(
            "exposure_vert",
            self.camera_interface,
            "exposure_vert",
            default=constants.DEFAULT_CAMERA_EXPOSURE_TIME,
            description="Vertical camera exposure time",
            unit="us",
        )
        self.exposure_horiz: FloatParamHandle
        self.exposure_vert: FloatParamHandle

        self.setattr_param_rebind("injection_aom_static_frequency", self.red_mot)
        self.setattr_param_rebind(
            "red_broadband_time",
            self.red_mot.broadband_red_phase,
            "duration",
            description="Broadband phase duration",
        )
        self.red_broadband_time: FloatParamHandle

        self.hook_setup_andor()

    def hook_setup_andor(self):
        """
        Setup the Andor camera

        This is a method so that children classes can override it
        """
        self.setattr_fragment("andor_camera_control", AndorCameraControl)
        self.andor_camera_control: AndorCameraControl

        self.setattr_result("andor_sum", FloatChannel, display_hints={"priority": -1})
        self.setattr_result("andor_mean", FloatChannel)
        self.andor_sum: FloatChannel
        self.andor_mean: FloatChannel

    @kernel
    def _from_start_to_end_of_broadband_mot(self):
        self.blue_3d_mot.load_mot(clearout=True)
        self.blue_3d_mot.turn_off_3d_and_2d_beams()
        self.red_mot.prepare_for_broadband_phase()
        self.red_mot.broadband_red_phase.do_phase()

    @kernel
    def _expand_and_image(self):
        self.red_mot.red_beam_controller.turn_off_mot_beams()

        delay(self.expansion_time.get())

        with parallel:
            self.andor_camera_control.trigger(
                exposure=self.fluorescence_pulse.fluorescence_pulse_duration.get(),
                control_shutter=True,
            )
            self.fluorescence_pulse.do_imaging_pulse()
            self.camera_interface.trigger()

        # Turn the fields back to defaults so eddy currents are gone by the next shot
        delay(1e-3)
        self.blue_3d_mot.enable_mot_fields()

    @kernel
    def _save_data(self):
        "Consume all slack and save the photos"
        self.core.wait_until_mu(now_mu())
        self.camera_interface.save_data()
        sums = [0]
        means = [0.0]
        self.andor_camera_control.readout_ROIs(
            sums,
            means,
            timeout_mu=self.core.get_rtio_counter_mu() + self.core.seconds_to_mu(1.0),
        )
        self.andor_sum.push(sums[0])
        self.andor_mean.push(means[0])


class MeasureBBRedMOTFrag(RedMOTBase):
    @kernel
    def run_once(self):
        self.core.break_realtime()
        self._from_start_to_end_of_broadband_mot()
        self._expand_and_image()
        self._save_data()


class MeasureNarrowbandMOTFrag(RedMOTBase):
    @kernel
    def run_once(self):
        narrowband_duration = self.red_mot.get_total_narrowband_duration()

        self.core.break_realtime()

        self._from_start_to_end_of_broadband_mot()

        with parallel:
            with sequential:
                delay(narrowband_duration)
                self._expand_and_image()

            self.red_mot.transition_broadband_to_narrowband()

        self._save_data()


MeasureBBRedMOT = make_fragment_scan_exp(MeasureBBRedMOTFrag)
MeasureNarrowbandRedMOT = make_fragment_scan_exp(MeasureNarrowbandMOTFrag)
