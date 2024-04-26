from artiq.experiment import *


class Test(EnvExperiment):
    """TEST - all devices"""

    # printing must be off the kernel
    @rpc(flags={"async"})
    def prnt(self, channel, adc):
        print(
            "{} ADC: {}".format(channel, adc),
            end="\r",
        )

    def build(self):
        self.setattr_device("core")

        # LED
        self.setattr_device("led0")
        self.setattr_device("led1")

        # TTL
        self.ttlOut = [None] * 4
        self.ttl = [None] * 12
        for i in range(4):
            self.setattr_device("ttl" + str(i))
            self.ttlOut[i] = self.__dict__["ttl" + str(i)]
        for i in range(12):
            self.setattr_device("ttl" + str(i + 4))
            self.ttl[i] = self.__dict__["ttl" + str(i + 4)]

        # Fastino
        self.setattr_device("fastino")

        # Mirny
        self.setattr_device("mirny_cpld")
        self.mirny_ch = [None] * 4
        self.ttl_mirny_sw = [None] * 4
        for i in range(4):
            self.setattr_device(f"mirny_ch{i}")  # ADF5356
            self.mirny_ch[i] = self.__dict__[f"mirny_ch{i}"]
            self.setattr_device(f"ttl_mirny_sw{i}")  # TTLOut
            self.ttl_mirny_sw[i] = self.__dict__[f"ttl_mirny_sw{i}"]

        # Almazny
        self.setattr_device("almazny")

        # SUServo
        self.setattr_device("suservo")
        self.suservo_ch = [None] * 8
        for i in range(8):
            self.setattr_device(f"suservo_ch{i}")  # SUServo Channel
            self.suservo_ch[i] = self.__dict__[f"suservo_ch{i}"]

        self.urukul_cpld = [None] * 2
        self.urukul_dds = [None] * 2
        for i in range(2):
            self.setattr_device("urukul" + str(i) + "_cpld")  # CPLD
            self.urukul_cpld[i] = self.__dict__[f"urukul{i}_cpld"]
            self.setattr_device(f"urukul{i}_dds")  # AD9910
            self.urukul_dds[i] = self.__dict__[f"urukul{i}_dds"]

    @kernel
    def run(self):
        self.init()
        self.test()

    @kernel
    def init(self):
        """Call the init() method of each device in the device_db."""
        self.core.break_realtime()
        self.core.reset()

        # Fastino
        self.fastino.init()
        print("fastino (Fastino) initialised")
        delay(100 * ms)

        # Mirny
        self.mirny_cpld.init()
        print("mirny (Mirny) initialised")
        delay(100 * ms)
        for mirny_ch in self.mirny_ch:
            mirny_ch.init()
            delay(100 * ms)
        print("mirny (ADF5356) initialised")
        self.almazny.init()
        print("almazny (Almazny) initialised")
        delay(100 * ms)

        # SUServo
        self.suservo.init()
        print("suservo (SUServo) initialised")
        delay(100 * ms)

        # Urukul
        for i in range(2):
            self.urukul_cpld[i].init(blind=True)
            delay(100 * ms)
            self.urukul_dds[i].init(blind=True)
            delay(100 * ms)
        print("urukuls initialised")

    @kernel
    def test(self):
        self.core.break_realtime()

        # user LEDs
        self.led0.on()
        self.led1.on()

        # Suservo
        for i in range(8):
            self.suservo_ch[i].set_dds(profile=0, frequency=10e6 * (1 + i), offset=0.0)
            delay(100 * ms)
            self.suservo_ch[i].set(en_out=1, en_iir=0, profile=0)
            delay(100 * ms)
            self.prnt(i, self.suservo.get_adc(i))
            delay(100 * ms)

        # Mirny
        for i in range(4):
            self.ttl_mirny_sw[i].on()
            delay(100 * ms)
            self.mirny_ch[i].set_frequency(100e6 * (1 + i))
            delay(100 * ms)
        self.almazny.output_toggle(True)

        # Fastino
        self.fastino.set_leds(0b11111111)

        # TTL
        for i in range(4):
            self.ttlOut[i].output()
            delay(100 * ms)
            self.ttlOut[i].on()
            delay(100 * ms)
        for i in range(12):
            self.ttl[i].output()
            delay(100 * ms)
            self.ttl[i].on()
            delay(100 * ms)
        
        print("Test completed")