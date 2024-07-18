"""
The startup sequence for the experiment.
"""
from artiq.experiment import *

class LED(EnvExperiment):
    def build(self):
        print("Creating all devices...")
        self.setattr_device("core")

        # LEDs
        self.setattr_device("led0")
        self.setattr_device("led1")
        self.setattr_device("led2")
        self.led = [self.__dict__["led" + str(i)] for i in range(3)]  # TTLOut

        # TTLs
        for i in range(4):
            self.setattr_device("ttl" + str(i))
        for i in range(12):
            self.setattr_device("ttl" + str(i + 4))
        self.ttlOut = [self.__dict__["ttl" + str(i)] for i in range(4)]  # TTLOut
        self.ttl = [self.__dict__["ttl" + str(i + 4)] for i in range(12)]  # TTLInOut

        # Fastino
        self.setattr_device("fastino")

        # Mirny with mezzanine board
        self.setattr_device("mirny_cpld")
        for i in range(4):
            self.setattr_device(f"mirny_ch{i}")
        self.mirnies = [self.__dict__[f"mirny_ch{i}"] for i in range(4)]  # ADF5356

        # SUServo
        self.setattr_device("suservo")
        for i in range(8):
            self.setattr_device(f"suservo_ch{i}")  # SUServo Channel
        self.suservo_ch = [self.__dict__[f"suservo_ch{i}"] for i in range(8)]  # Channel

        print("All devices created.")
        """
        We are left with the following devices:

            self.led: [TTLOut]*2

            self.ttlOut: [TTLOut]*4
            self.ttl: [TTLInOut]*12

            self.fastino: Fastino

            self.mirny_cpld: Mirny
            self.mirnies: [ADF5356]*4
            self.almazny: Almazny

            self.suservo: SUServo
            self.suservo_ch: [Channel]*8
        """

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
        for ttl in self.ttl[:-4]:
            ttl.output()
            delay(100 * us)
            ttl.off()
            delay(100 * us)
        for ttl in self.ttl[-4:]:
            ttl.input()
            delay(100 * us)

        # Fastino
        self.fastino.init()
        delay(200 * us)
        self.fastino.set_leds(0b00000000)
        delay(100 * us)
        for dac in range(32):
            self.fastino.set_dac(dac, 0)
            delay(100 * us)

        # Mirny
        self.mirny_cpld.init()
        delay(200 * ms)
        for mirny in self.mirnies:
            mirny.init()
            mirny.sw.off()
            delay(200 * ms)

        # SUServo
        self.suservo.init()
        delay(200 * ms)

        self.core.wait_until_mu(now_mu())
        """
        We are left with the following devices:

            self.led: [TTLOut]*2
                set to off

            self.ttlOut: [TTLOut]*4
            self.ttl: [TTLInOut]*12
                set to outputs (off) except for the last 4

            self.fastino: Fastino
                LEDs on, DACs zeroed

            self.mirny_cpld: Mirny
            self.mirnies: [ADF5356]*4
            self.almazny: Almazny
                all channels off

            self.suservo: SUServo
            self.suservo_ch: [Channel]*8
                disabled with profile configurations left as previously set
        """
