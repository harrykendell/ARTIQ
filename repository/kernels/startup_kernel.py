"""
The startup sequence for the experiment.
"""

from artiq.experiment import *
from artiq.language.core import delay, now_mu
from artiq.language.units import us, ms
from artiq.coredevice.ttl import TTLOut, TTLInOut
from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo
from artiq.coredevice.fastino import Fastino

import logging


class Startup(EnvExperiment):
    def build(self):
        logging.debug("Building startup kernel...")
        self.core: Core = self.get_device("core")

        # LEDs
        self.led0: TTLOut = self.get_device("led0")
        self.led1: TTLOut = self.get_device("led1")
        self.led2: TTLOut = self.get_device("led2")
        self.led: list[TTLOut] = [self.__dict__["led" + str(i)] for i in range(3)]

        # TTLs - we have 4 that are output only and 12 that are input/output
        for i in range(4):
            self.setattr_device("ttl" + str(i))
        self.ttlOut: list[TTLOut] = [self.__dict__["ttl" + str(i)] for i in range(4)]

        for i in range(12):
            self.setattr_device("ttl" + str(i + 4))
        self.ttl: list[TTLInOut] = [
            self.__dict__["ttl" + str(i + 4)] for i in range(12)
        ]

        # Fastino
        self.fastino: Fastino = self.get_device("fastino")

        # SUServo
        self.suservo: SUServo = self.get_device("suservo")

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
            ttlo.off()
            delay(100 * us)
        for ttl in self.ttl:
            ttl.output()
            delay(100 * us)
            ttl.off()
            delay(100 * us)

        # Fastino
        self.fastino.init()
        delay(100 * ms)

        # SUServo
        self.suservo.init()
        delay(100 * ms)

        self.core.wait_until_mu(now_mu())
