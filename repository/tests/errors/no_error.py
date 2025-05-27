from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.experiment import EnvExperiment, kernel


class NoErrorInKernel(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("suservo_aom_MOT")
        self.suservo_aom_MOT: SUServoChannel

    @kernel
    def run(self):

        self.core.reset()
        # this ki is valid so wont raise ValueError inside the kernel
        self.suservo_aom_MOT.set_iir(profile=1, adc=1, kp=-0.001, ki=0.0)
