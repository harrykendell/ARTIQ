import logging
import time

import pandas as pd
from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import rpc
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle
from ndscan.experiment.result_channels import OpaqueChannel
from utils.suservo import LibSetSUServoStatic
from retry import retry

from icl_repo.lib.fragments.cameras.flir_camera import Chamber2HorizontalCamera


class TestFLIRCamera(EnvExperiment):
    def run(self):
        # This import happens here because, for some reason, importing the
        # gi.repository Aravis (which happens in python-aravis) breaks if you do
        # it from multiple processes at the same time, which ARTIQ will trigger
        # when scanning for experiments
        from aravis import Camera

        cam = Camera("FLIR-Blackfly S BFS-PGE-50S5M-22018873", loglevel=logging.INFO)
        cam.start_acquisition_trigger()

        cam.trigger()

        frame = self.get_frame(cam)

        print(frame)

    @retry(delay=1e-3, tries=1000)
    def get_frame(self, cam):
        f = cam.try_pop_frame()
        if f is None:
            raise RuntimeError
        return f


class TestFLIRCameraInterface(ExpFragment):
    def build_fragment(self):
        self.setattr_fragment("cam", Chamber2HorizontalCamera)
        self.cam: Chamber2HorizontalCamera

    def host_setup(self):
        super().host_setup()

        self.cam.ready_for_trigger(exposure_us=1000, num_images=3)

        for _ in range(3):
            self.cam.trigger()
            time.sleep(0.1)

        frames = self.cam.get_frames()

        print(f"Got {len(frames)} frames:")

        for ts, frame in frames:
            print(pd.Timedelta(ts, "ns"))
            print(frame)


class TestFLIRHardwareTrigger(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("cam", Chamber2HorizontalCamera, hardware_trigger=True)
        self.cam: Chamber2HorizontalCamera
        self.ttl_trigger = self.get_device("ttl_camera_trigger_horizontal")

    def host_setup(self):
        super().host_setup()

        self.cam.ready_for_trigger(exposure_us=1000, num_images=3)

    @kernel
    def take_photos(self):
        self.core.reset()

        for _ in range(3):
            self.ttl_trigger.pulse(1e-3)
            delay(10e-3)

        self.core.wait_until_mu(now_mu())

    def run_once(self):
        self.take_photos()

        frames = self.cam.get_frames()

        print(f"Got {len(frames)} frames:")

        for ts, frame in frames:
            print(pd.Timedelta(ts, "ns"))
            print(frame)


class TestFLIRAgainstLightBG(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("cam", Chamber2HorizontalCamera)
        self.cam: Chamber2HorizontalCamera

        self.setattr_fragment(
            "suservo_setter",
            LibSetSUServoStatic,
            "suservo_aom_singlepass_461_3DMOT_axialplus",
        )
        self.suservo_setter: LibSetSUServoStatic

        self.setattr_param(
            "amplitude", FloatParam, "AOM amplitude", default=1, max=1, min=0
        )
        self.amplitude: FloatParamHandle

        self.setattr_result("image", OpaqueChannel)
        self.image: OpaqueChannel

    @rpc
    def setup_camera(self):
        self.cam.ready_for_trigger(exposure_us=1000, num_images=1)

    @rpc
    def get_frame(self):
        self.cam.trigger()
        _, image = self.cam.get_one_frame(timeout=1)
        self.image.push(image)

    @kernel
    def run_once(self):
        self.setup_camera()

        self.core.break_realtime()
        self.suservo_setter.set_suservo(
            150e6, amplitude=self.amplitude.get(), attenuation=20.0
        )

        delay(250e-3)
        self.core.wait_until_mu(now_mu())

        self.get_frame()


TestFLIRCameraInterface = make_fragment_scan_exp(TestFLIRCameraInterface)
TestFLIRAgainstLightBG = make_fragment_scan_exp(TestFLIRAgainstLightBG)
TestFLIRHardwareTrigger = make_fragment_scan_exp(TestFLIRHardwareTrigger)
