"""
The startup sequence for the experiment.
"""
from artiq.experiment import *
from artiq.coredevice.fastino import Fastino
from artiq.coredevice.ttl import TTLOut, TTLInOut
from artiq.coredevice.core import Core
from artiq.coredevice.almazny import AlmaznyLegacy
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.mirny import Mirny

import sys

sys.path.append(
    __file__.split("repository")[0] + "repository"
)  # link to repository root
from utils.SUServoManager import SUServoManager
from utils.MirnyManager import MirnyManager

class Startup(EnvExperiment):
    def build(self):
        print("Creating all devices...")
        self.setattr_device("core")

        # LEDs
        self.led0: TTLOut = self.get_device("led0")
        self.led1: TTLOut = self.get_device("led1")
        self.led2: TTLOut = self.get_device("led2")
        self.led: list[TTLOut] = [self.__dict__["led" + str(i)] for i in range(3)]  # TTLOut

        # TTLs
        for i in range(4):
            self.setattr_device("ttl" + str(i))
        for i in range(12):
            self.setattr_device("ttl" + str(i + 4))
        self.ttlOut: list[TTLOut] = [self.__dict__["ttl" + str(i)] for i in range(4)]  # TTLOut
        self.ttl: list[TTLInOut] = [self.__dict__["ttl" + str(i + 4)] for i in range(12)]  # TTLInOut

        # Fastino
        self.fastino: Fastino = self.get_device("fastino")

        # Mirny with mezzanine board
        self.mirny: Mirny = self.get_device('mirny_cpld')
        self.mirny_chs: list[ADF5356] = [self.get_device(f"mirny_ch{i}") for i in range(4)]
        self.almazny: AlmaznyLegacy = self.get_device("mirny_almazny")

        # SUServo
        self.suservo = self.get_device("suservo")
        self.suservo_chs = [self.get_device(f"suservo_ch{i}") for i in range(8)]

        print("All devices created.")

    @kernel
    def run(self):
        self.core.reset()
        print("Initialising all devices...")
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
        delay(200 * us)
        self.fastino.set_leds(0b00000000)
        delay(100 * us)
        for dac in range(32):
            self.fastino.set_dac(dac, dac / 10.0)
            delay(100 * us)

        # SUServo
        self.core.break_realtime()
        self.suservo.init()

        # Mirny
        self.core.break_realtime()
        self.mirny.init()
        delay(100 * us)
        for mch in range(4):
            self.mirny_chs[mch].init()
            delay(100 * us)

        self.core.break_realtime()
        self.almazny.init()
        self.core.break_realtime()

        print("All devices initialised.")
        self.core.wait_until_mu(now_mu())
