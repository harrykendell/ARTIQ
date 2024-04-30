"""
The idle sequence for the experiment.
"""

from artiq.experiment import *


class Idle(EnvExperiment):

    def build(self):
        self.setattr_device("core")
        self.setattr_device("led0")

    @kernel
    def run(self):
        self.core.reset()

        self.led0.on()
        delay(0.5 * s)
        self.led0.off()
        delay(0.5 * s)

        # Wait for idle to finish
        self.core.wait_until_mu(now_mu())
