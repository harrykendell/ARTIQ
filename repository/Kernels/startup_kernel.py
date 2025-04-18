"""
The startup sequence for the experiment.
"""

from artiq.experiment import EnvExperiment, kernel
from artiq.language.core import delay, now_mu
from artiq.language.units import us, ms
from artiq.coredevice.ttl import TTLOut, TTLInOut
from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo
from artiq.coredevice.fastino import Fastino
from artiq.coredevice.mirny import Mirny
from artiq.coredevice.adf5356 import ADF5356 as MirnyChannel

import logging


class Startup(EnvExperiment):
    def build(self):
        logging.debug("Building startup kernel...")
        self.core: Core = self.get_device("core")

        # LEDs
        self.led: list[TTLOut] = [self.get_device("led" + str(i)) for i in range(3)]

        # TTLs - we have 4 that are output only and 12 that are input/output
        self.ttlOut: list[TTLOut] = [self.get_device("ttl" + str(i)) for i in range(4)]

        self.ttl: list[TTLInOut] = [
            self.get_device("ttl" + str(i + 4)) for i in range(12)
        ]

        # Fastino
        self.fastino: Fastino = self.get_device("fastino")

        # SUServo
        self.suservo: SUServo = self.get_device("suservo")

        # Mirny
        self.mirny_cpld: Mirny = self.get_device("mirny_cpld")
        self.mirny_ch: list[MirnyChannel] = [
            self.get_device("mirny_ch" + str(i)) for i in range(4)
        ]

    @kernel
    def run(self):
        # TODO: This should really setup according to devices.py defaults

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

        # Mirny
        self.mirny_cpld.init()
        delay(100 * ms)
        for ch in self.mirny_ch:
            ch.init()
            delay(100 * ms)

        self.core.wait_until_mu(now_mu())
