import logging

import numpy as np
from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import kernel
from artiq.experiment import ms
from artiq.experiment import now_mu
from artiq.experiment import parallel
from artiq.experiment import rpc
from ndscan.experiment import ExpFragment
from ndscan.experiment import ResultChannel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import BoolParam
from ndscan.experiment.parameters import BoolParamHandle
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from icl_repo.lib.fragments.blue_3d_mot import Blue3DMOTFrag
from icl_repo.lib.fragments.cameras.dual_camera_measurer import DualCameraMeasurement
from icl_repo.lib.fragments.fluorescence_pulse import ImagingFluorescencePulse

logger = logging.getLogger(__name__)


class _MeasureBlueMOTFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("mot_controller", Blue3DMOTFrag, manual_init=True)
        self.mot_controller: Blue3DMOTFrag

        self.setattr_param_rebind(
            "mot_loading_time", self.mot_controller, "loading_time"
        )
        self.mot_loading_time: FloatParamHandle

        self.setattr_param(
            "delay_between_points",
            FloatParam,
            "Delay between measurements",
            default=0,
            min=0,
            unit="s",
        )
        self.delay_between_points: FloatParamHandle

        self.setattr_param(
            "clearout",
            BoolParam,
            "Clear out atoms between shots",
            default="True",
        )
        self.clearout: BoolParamHandle

        self.first_run = True

    @kernel
    def _take_data(self, loading_time):
        raise NotImplementedError

    @kernel
    def run_once(self):
        self.core.break_realtime()

        if self.first_run or self.clearout.get():
            self.first_run = False

            self.mot_controller.init()
            self.mot_controller.enable_mot_fields()
            self.mot_controller.clear_ch2()

        # Delay long enough that we can write shutter closures into the past
        delay(self.mot_controller.mot_all_beam_setter.get_longest_shutter_delay())

        self._before_start_load_hook()

        # Load MOT and start measuring signal immediately
        if self.clearout.get():
            self.mot_controller.turn_on_all_beams()
        else:
            # If clearout was not requested, we'll not change the AOM levels
            # unless this is called at some point so do so now
            self.mot_controller.all_beam_default_setter.turn_on_all(light_enabled=True)

        self._take_data(self.mot_loading_time.get())

        delay(self.delay_between_points.get())
        self.core.wait_until_mu(now_mu())

    @kernel
    def _before_start_load_hook(self):
        pass


class MeasureBlueMOTWithCameraFrag(_MeasureBlueMOTFrag):
    def build_fragment(self):
        self.setattr_fragment(
            "dual_cameras", DualCameraMeasurement, hardware_trigger=True
        )
        self.dual_cameras: DualCameraMeasurement

        self.setattr_param_rebind(
            "exposure",
            self.dual_cameras,
            "exposure_horiz",
            description="Camera exposures",
        )
        self.exposure: FloatParamHandle

        self.dual_cameras.bind_param("exposure_vert", self.exposure)

        super().build_fragment()

    @kernel
    def _take_data(self, loading_time):
        delay(loading_time)

        self.dual_cameras.trigger()

        self.core.wait_until_mu(now_mu())

        self.dual_cameras.save_data()


class MeasureBlueMOTWithExpansionFrag(_MeasureBlueMOTFrag):
    def build_fragment(self):
        self.setattr_fragment(
            "dual_cameras", DualCameraMeasurement, hardware_trigger=True
        )
        self.dual_cameras: DualCameraMeasurement

        self.setattr_param_rebind(
            "exposure",
            self.dual_cameras,
            "exposure_horiz",
            description="Camera exposures",
        )
        self.exposure: FloatParamHandle

        self.dual_cameras.bind_param("exposure_vert", self.exposure)

        self.setattr_param(
            "expansion_time",
            FloatParam,
            description="Expansion time of MOT",
            default=0.0,
            unit="us",
        )
        self.expansion_time: FloatParamHandle

        self.setattr_fragment("fluorescence_pulse", ImagingFluorescencePulse)
        self.fluorescence_pulse: ImagingFluorescencePulse

        super().build_fragment()

    @kernel
    def _take_data(self, loading_time):
        delay(loading_time)
        self.mot_controller.turn_off_3d_and_2d_beams()
        delay(self.expansion_time.get())

        with parallel:
            self.dual_cameras.trigger()
            self.fluorescence_pulse.do_imaging_pulse()

        self.core.wait_until_mu(now_mu())

        self.dual_cameras.save_data()


MeasureBlueMOTWithCamera = make_fragment_scan_exp(MeasureBlueMOTWithCameraFrag)
MeasureBlueMOTWithExpansion = make_fragment_scan_exp(MeasureBlueMOTWithExpansionFrag)
