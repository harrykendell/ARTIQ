import logging

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.suservo import SUServo
from artiq.experiment import delay_mu
from artiq.experiment import kernel
from ndscan.experiment import EnumerationValue
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle
from utils.suservo import LibSetSUServoStatic
from utils.get_local_devices import get_local_devices

logger = logging.getLogger(__name__)


class FlashSUServo(ExpFragment):
    """
    Flash a SUServo channel at a rate
    """

    def build_fragment(self):
        self.setattr_param(
            "frequency",
            FloatParam,
            description="Static frequency of the SUServo channel",
            default=100e6,
            min=0,
            max=400e6,  # from AD9910 specs
            unit="MHz",
            step=1,
            # precision=2,
        )

        self.setattr_param(
            "amplitude",
            FloatParam,
            description="Amplitude of AD9910 output, from 0 to 1",
            default=1.0,
            min=0,
            max=1,
            # precision=1,
        )
        self.setattr_param(
            "attenuation",
            FloatParam,
            description="Attenuation on Urukul's variable attenuator",
            default=30,
            unit="dB",
            min=0,
            max=31.5,
            # precision=1,
        )

        self.setattr_param(
            "flash_rate",
            FloatParam,
            description="Flash rate",
            default=100,
            min=0,
            max=2e6,
            unit="Hz",
            step=1,
        )

        suservo_channels = get_local_devices(self, SUServoChannel)
        self.setattr_argument(
            "channel", EnumerationValue(suservo_channels, default=suservo_channels[0])
        )

        self.setattr_fragment("LibSetSUServoStatic", LibSetSUServoStatic, self.channel)

        self.setattr_device("core")

        self.core: Core
        self.amplitude: FloatParamHandle
        self.frequency: FloatParamHandle
        self.attenuation: FloatParamHandle
        self.flash_rate: FloatParamHandle
        self.channel: str
        self.LibSetSUServoStatic: LibSetSUServoStatic

    def host_setup(self):
        super().host_setup()

        self.suservo_channel: Channel = self.get_device(self.channel)
        self.suservo: SUServo = self.suservo_channel.servo

        self.print_debug_statements = logger.isEnabledFor(logging.DEBUG)

        self.toggle_half_period_mu = self.core.seconds_to_mu(
            0.5 / self.flash_rate.get()
        )

    @kernel
    def run_once(self):
        # Set up the suservo output
        self.LibSetSUServoStatic.set_suservo(
            self.frequency.get(), self.amplitude.get(), self.attenuation.get()
        )

        # Toggle it forever
        while True:
            self.suservo_channel.set(en_out=1, en_iir=0, profile=0)
            delay_mu(self.toggle_half_period_mu)
            self.suservo_channel.set(en_out=0, en_iir=0, profile=0)
            delay_mu(self.toggle_half_period_mu)


FlashSUServoExp = make_fragment_scan_exp(FlashSUServo)
