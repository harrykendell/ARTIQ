from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.ad9912 import AD9912
from artiq.experiment import *
from utils.get_local_devices import get_local_devices


class TurnOn1064Temporary(EnvExperiment):
    """
    Turn on the temporary 1064 AOMs
    """

    def build(self):
        self.setattr_device("urukul_aom_1064_delivery")
        self.setattr_device("urukul_aom_1064_switch")

        self.setattr_argument(
            "frequency_delivery", NumberValue(default=110e6, unit="MHz")
        )
        self.setattr_argument(
            "attenuation_delivery", NumberValue(default=30, unit="dB", min=0, max=30)
        )

        self.setattr_argument(
            "frequency_switch", NumberValue(default=110e6, unit="MHz")
        )
        self.setattr_argument(
            "attenuation_switch", NumberValue(default=30, unit="dB", min=0, max=30)
        )

        self.channel_delivery: AD9912 = self.urukul_aom_1064_delivery
        self.channel_switch: AD9912 = self.urukul_aom_1064_switch
        self.setattr_device("core")

    @kernel
    def run(self):
        self.core.break_realtime()

        self.channel_delivery.cpld.init()
        self.channel_switch.cpld.init()
        self.channel_delivery.init()
        self.channel_switch.init()

        self.channel_delivery.cfg_sw(True)
        self.channel_delivery.set(self.frequency_delivery)
        self.channel_delivery.set_att(self.attenuation_delivery)

        self.channel_switch.cfg_sw(True)
        self.channel_switch.set(self.frequency_switch)
        self.channel_switch.set_att(self.attenuation_switch)
