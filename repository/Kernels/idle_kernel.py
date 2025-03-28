from artiq.experiment import *
from artiq.language.units import ms
from artiq.language.core import now_mu, delay, parallel

import logging

class Idle(EnvExperiment):
    # The idle sequence for the experiment.
    def build(self):
        self.setattr_device("core")
        self.setattr_device("led1")
        self.setattr_device("led2")

    @kernel
    def run(self):
        start_time = now_mu() + self.core.seconds_to_mu(500*ms)
        while self.core.get_rtio_counter_mu() < start_time:
            pass
        self.core.reset()
        self.core.break_realtime()

        while True:
            with parallel:
                self.led1.pulse(250*ms)
                self.led2.pulse(250*ms)
            delay(125*ms)
            self.led1.pulse(125*ms)
            delay(125*ms)
            self.led1.pulse(125*ms)
            delay(250*ms)

