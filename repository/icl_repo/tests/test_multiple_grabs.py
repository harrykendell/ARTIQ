from artiq.coredevice.core import Core
from artiq.experiment import *
from ndscan.experiment import *
from ndscan.experiment import FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle
from ndscan.experiment.parameters import IntParamHandle

from icl_repo.lib.fragments.cameras.andor_camera import AndorCameraControl


class MultipleGrabs(ExpFragment):
    def build_fragment(self, *args, **kwargs) -> None:
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("andor_interface", AndorCameraControl)
        self.andor_interface: AndorCameraControl

        self.setattr_param(
            "delay",
            FloatParam,
            default=10e-3,
            description="Delay between images",
            unit="ms",
        )

        self.setattr_param(
            "num_triggers", IntParam, default=2, description="Num triggers"
        )
        self.num_triggers: IntParamHandle

        self.setattr_param("num_reads", IntParam, default=2, description="Num reads")
        self.num_reads: IntParamHandle

    @kernel
    def run_once(self) -> None:
        self.core.break_realtime()

        delay(1.0)

        for _ in range(self.num_triggers.get()):
            self.andor_interface.trigger(exposure=1e-6, control_shutter=False)
            delay(self.delay.get())

        sums = [0] * self.num_reads.get()
        means = [0.0] * self.num_reads.get()
        self.andor_interface.readout_ROIs(
            sums,
            means,
            timeout_mu=now_mu() + self.core.seconds_to_mu(1.0),
            num_rois=self.num_reads.get(),
        )

        print(sums)
        print(means)


MultipleGrabs = make_fragment_scan_exp(MultipleGrabs)
