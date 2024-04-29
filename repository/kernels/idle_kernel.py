from artiq.experiment import *
from time import sleep


class LED(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("led0")

    @kernel
    def run(self):
        self.core.break_realtime()
        self.led0.off()
        
        while True:
            self.led0.pulse(250 * ms)
            delay(0.5)
            self.core.break_realtime()
