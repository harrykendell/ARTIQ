from artiq.experiment import EnvExperiment, kernel
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.core import Core


class ErrorInKernel(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("suservo_aom_MOT")
        self.suservo_aom_MOT: SUServoChannel

    @kernel
    def run(self):
        self.core.reset()

        self.core.break_realtime()
        # this ki is invalid so causes a raise ValueError inside the kernel
        self.suservo_aom_MOT.set_iir(1, 1, -0.001, 1.0)
