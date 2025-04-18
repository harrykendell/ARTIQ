from artiq.experiment import EnvExperiment, kernel
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.core import Core


class NoErrorInKernel(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("suservo_aom_MOT")
        self.suservo_aom_MOT: SUServoChannel

    @kernel
    def run(self):
        self.core.reset()

        self.core.break_realtime()
        # this ki is valid so wont raise ValueError inside the kernel
        self.suservo_aom_MOT.set_iir(profile=1, adc=1, kp=-0.001, ki=0.0)
