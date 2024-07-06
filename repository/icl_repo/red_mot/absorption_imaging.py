import logging

from artiq.experiment import delay
from artiq.experiment import kernel
from ndscan.experiment import FloatChannel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from icl_repo.lib import constants
from icl_repo.lib.fragments.cameras.andor_camera import AndorCameraControl
from icl_repo.lib.fragments.cameras.triple_imaging_kinetics import (
    RedMOTWithExperiment,
)

logger = logging.getLogger(__name__)


class AbsorptionRedMOT(RedMOTWithExperiment):
    """
    Image red MOT with absorption
    """

    @kernel
    def do_spectroscopy_hook(self):
        pass

    def build_fragment(self):
        super().build_fragment()

        # Set the MOT field to off before the "spectroscopy" (i.e. imaging) starts
        self.override_param("spectroscopy_field_gradient", 0.0)

        # Disable unused params
        for p in ["delay_after_spectroscopy"]:
            self.override_param(p, 0)

        # %% Params

        self.setattr_param(
            "delay_between_absorption_pulses",
            FloatParam,
            "Delay after absorption pulse before second",
            default=30e-3,
            unit="ms",
        )
        self.delay_between_absorption_pulses: FloatParamHandle

        self.setattr_param(
            "delay_before_background_pulse",
            FloatParam,
            "Delay after absoprtion pulse before no-light background image",
            default=50e-3,
            unit="ms",
        )
        self.delay_before_background_pulse: FloatParamHandle

        # %% Results

        self.setattr_result("andor_sum_0", FloatChannel)
        self.setattr_result("andor_sum_1", FloatChannel)
        self.setattr_result("andor_sum_2", FloatChannel)
        self.setattr_result("andor_sum_3", FloatChannel)

        self.setattr_result("absorption", FloatChannel)

        self.andor_sum_0: FloatChannel
        self.andor_sum_1: FloatChannel
        self.andor_sum_2: FloatChannel
        self.andor_sum_3: FloatChannel

        self.absorption: FloatChannel

    def host_setup(self):
        andor_exposure = 2 * self.fluorescence_pulse.fluorescence_pulse_duration.get()
        logger.warning(
            "Please ensure that the Andor is in Kinetics mode (not Fast Kinetics) with NO EM GAIN!"
            " And that exposure is set to at least %f us",
            1e6 * andor_exposure,
        )

        return super().host_setup()

    @kernel
    def do_imaging_hook(self):
        """
        Hook for the imaging sequence. This hook runs after the spectroscopy
        etc. is completed, and should handle imaging with the Andor camera.
        """
        andor_exposure = 2 * self.fluorescence_pulse.fluorescence_pulse_duration.get()

        # Image with atoms
        self._do_pulse(andor_exposure)

        # Wait for atoms to disappear
        delay(self.delay_between_absorption_pulses.get())

        # Image without atoms
        self._do_pulse(andor_exposure)

        # Trigger the third time without any light
        delay(self.delay_before_background_pulse.get())
        self._do_pulse_no_light(andor_exposure)

        # Trigger again since we're still in fast kinetics mode so we must take two images
        delay(self.delay_between_absorption_pulses.get())
        self._do_pulse_no_light(andor_exposure)

    @kernel
    def _do_pulse_no_light(self, andor_exposure):
        delay(-0.5 * andor_exposure)
        self.andor_camera_control.trigger(
            exposure=andor_exposure,
            control_shutter=False,
        )
        delay(0.5 * andor_exposure)

    def hook_setup_andor(self):
        """
        Setup the Andor camera with default settings
        """
        self.setattr_fragment("andor_camera_control", AndorCameraControl)
        self.andor_camera_control: AndorCameraControl

    # def hook_setup_andor(self):
    #     """
    #     Setup the Andor camera to use 4x ROIs since we're expecting fast
    #     kinetics mode with 2x images which we'll repeat.

    #     Each image is the full sensor size, so we'll use the normal ROI

    #     TODO: Set up Fast Kinetics mode here too
    #     """

    #     self.setattr_fragment(
    #         "andor_camera_control",
    #         AndorCameraControl,
    #         roi_defaults=[
    #             [
    #                 constants.ANDOR_ROI_X0,
    #                 i * constants.ANDOR_SENSOR_HEIGHT + constants.ANDOR_ROI_Y0,
    #                 constants.ANDOR_ROI_X1,
    #                 i * constants.ANDOR_SENSOR_HEIGHT + constants.ANDOR_ROI_Y1,
    #             ]
    #             for i in range(2)
    #         ],
    #     )
    #     self.andor_camera_control: AndorCameraControl

    @kernel
    def save_data_hook(self):
        """
        Hook to save data from the Andor camera

        We took four images, each seperately as normal (i.e. not fast kinetics)
        images.
        """

        n = 4
        sums = [0] * n

        timeout_mu = self.core.get_rtio_counter_mu() + self.core.seconds_to_mu(1.0)

        for i in range(n):
            s = [0]
            m = [0.0]
            self.andor_camera_control.readout_ROIs(s, m, timeout_mu)
            sums[i] = s[0]

        self.andor_sum_0.push(sums[0])
        self.andor_sum_1.push(sums[1])
        self.andor_sum_2.push(sums[2])
        self.andor_sum_3.push(sums[3])

        self.absorption.push(sums[1] - sums[0])


AbsorptionRedMOTExp = make_fragment_scan_exp(AbsorptionRedMOT)
