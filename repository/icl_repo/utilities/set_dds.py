from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.ad9912 import AD9912
from artiq.experiment import *
from utils.get_local_devices import get_local_devices


class SetDDS(EnvExperiment):
    """
    Basic DDS setter for AD9910s or AD9912s
    """

    def build(self):
        list_of_channels = get_local_devices(self, AD9910) + get_local_devices(
            self, AD9912
        )
        self.setattr_argument(
            "device_name",
            EnumerationValue(list_of_channels, default=list_of_channels[0]),
        )

        self.setattr_argument("frequency", NumberValue(default=100e6, unit="MHz"))
        self.setattr_argument(
            "attenuation", NumberValue(default=30, unit="dB", min=0, max=30)
        )
        self.setattr_argument("switch", BooleanValue(default=True))

        self.channel: AD9912 = self.get_device(self.device_name)
        self.setattr_device("core")

    @kernel
    def run(self):
        self.core.break_realtime()

        self.channel.cpld.init()
        self.channel.init()

        self.channel.sw.set_o(self.switch)
        self.channel.set(self.frequency)
        self.channel.set_att(self.attenuation)
