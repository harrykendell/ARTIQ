import logging

from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.core import Core
from artiq.coredevice.mirny import Mirny
from artiq.experiment import EnumerationValue
from artiq.experiment import kernel
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import BoolParam
from ndscan.experiment.parameters import FloatParam
from utils.get_local_devices import get_local_devices


logger = logging.getLogger(__name__)


class SetMirnyFrag(ExpFragment):
    """
    Set a Mirny frequency
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        mirny_channels = get_local_devices(self, ADF5356)
        if not mirny_channels:
            raise ValueError("No Mirny channels found in device_db")
        self.setattr_argument(
            "channel",
            EnumerationValue(mirny_channels, default=mirny_channels[0]),
        )
        self.channel: str

        self.setattr_param(
            "frequency",
            FloatParam,
            "Static frequency of the Mirny channel",
            unit="MHz",
            default=80e6,
            step=1,
        )

        self.setattr_param(
            "attenuation",
            FloatParam,
            "Attenuation on Mirny output",
            unit="dB",
            default=30,
        )

        self.setattr_param(
            "rf_sw",
            BoolParam,
            "RF switch state",
            default="True",
        )

        self.setattr_param(
            "initiate_mirny",
            BoolParam,
            "Call mirny.init()",
            default="True",
        )

    def host_setup(self):
        super().host_setup()

        logger.info("Setting mirny %s", self.channel)

        self.mirny_channel: ADF5356 = self.get_device(self.channel)
        self.mirny: Mirny = self.mirny_channel.cpld

        self._init_completed = False

    @kernel
    def device_setup(self):
        self.device_setup_subfragments()

        if not self._init_completed:
            self.core.break_realtime()

            if self.initiate_mirny.get():
                self.mirny.init()

            self.mirny_channel.init()

            self._init_completed = True

    @kernel
    def run_once(self) -> None:
        self.core.break_realtime()

        self.mirny_channel.set_frequency(self.frequency.get())
        self.mirny_channel.set_att(self.attenuation.get())
        self.mirny_channel.sw.set_o(self.rf_sw.get())


SetMirny = make_fragment_scan_exp(SetMirnyFrag)
