"""
The startup sequence for the experiment.
"""

from artiq.experiment import *
from artiq.language.core import delay, now_mu
from artiq.language.units import us
from artiq.coredevice.ttl import TTLOut, TTLInOut
from artiq.coredevice.core import Core

import logging


class Startup(EnvExperiment):
    def build(self):
        logging.debug("Building startup kernel...")
        self.core: Core = self.get_device("core")

        # LEDs
        self.led0: TTLOut = self.get_device("led0")
        self.led1: TTLOut = self.get_device("led1")
        self.led2: TTLOut = self.get_device("led2")
        self.led: list[TTLOut] = [
            self.__dict__["led" + str(i)] for i in range(3)
        ]  # TTLOut

        # TTLs
        for i in range(4):
            self.setattr_device("ttl" + str(i))
        for i in range(12):
            self.setattr_device("ttl" + str(i + 4))
        self.ttlOut: list[TTLOut] = [
            self.__dict__["ttl" + str(i)] for i in range(4)
        ]  # TTLOut
        self.ttl: list[TTLInOut] = [
            self.__dict__["ttl" + str(i + 4)] for i in range(12)
        ]  # TTLInOut

        logging.warning(
            "\n\nI should really set the state to the config values somehow, while updating the dataset\n\n"
        )

    @kernel
    def run(self):
        self.core.reset()
        self.core.break_realtime()
        # LEDs
        for led in self.led:
            led.on()

        # TTLs
        for ttlo in self.ttlOut:
            ttlo.output()
            delay(100 * us)
        for ttl in self.ttl:
            ttl.output()
            delay(100 * us)

        self.core.wait_until_mu(now_mu())
