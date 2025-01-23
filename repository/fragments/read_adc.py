import logging
from typing import Optional

from artiq.coredevice.core import Core
from artiq.coredevice.sampler import Sampler
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.suservo import SUServo
from artiq.experiment import StringValue
from artiq.experiment import kernel
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import IntParam
from ndscan.experiment.parameters import IntParamHandle
from repository.utils import get_local_devices

logger = logging.getLogger(__name__)


class ReadADC(Fragment):
    """
    Interface to read a voltage from an ARTIQ ADC

    This is an interface - you cannot use it directly and must use concrete
    implementations instead. This class defines a simple interface for taking a
    single reading from an ADC, abstracting away the details. Currently, the
    only possible ADC types are Samplers and SUServos - see
    :class:`~.ReadSamplerADC` and :class:`~.ReadSUServoADC`.
    """

    def build_fragment(self, *args, **kwargs):
        raise NotImplementedError

    def read_adc(self) -> float:
        raise NotImplementedError


class ReadSamplerADC(ReadADC):
    """
    Reads the voltage on a Sampler input channel

    The device and channel to be read are passed as arguments to :meth:`.build_fragment`, e.g.::

        self.setattr_fragment(
            "ReadSamplerADC", ReadSamplerADC, "sampler0", 2,
        )
    """

    def build_fragment(
        self,
        sampler_device: Optional[Sampler] = None,
        sampler_channel: Optional[int] = None,
        sampler_pgia_gain: Optional[int] = None,  #  0,1,2 or 3
    ):
        """
        Build this (sub)fragment

        If sampler_device and sampler_channel are provided then this fragment will have no parameters.
        Otherwise, it will expose these as ndscan parameters instead.
        """
        if sampler_channel is not None:
            self.sampler_channel: int = sampler_channel
        else:
            self.setattr_param(
                "sampler_channel_number",
                IntParam,
                description="Sampler channel to read",
                default=0,
                min=0,
                max=7,
            )
            self.sampler_channel_number: IntParamHandle

        if sampler_channel is not None:
            self.sampler_device: Sampler = sampler_device
        else:
            first_sampler_in_devicedb = get_local_devices(self, Sampler)[0]
            self.setattr_argument(
                "sampler_device_name",
                StringValue(default=first_sampler_in_devicedb),
                tooltip="Sampler device to read",
            )
            self.sampler_device_name: str

            self.sampler_device: Sampler = self.get_device(self.sampler_device_name)

        if sampler_pgia_gain is not None:
            self.sampler_pgia_gain_value = sampler_pgia_gain
        else:
            self.setattr_param(
                "sampler_channel_gain",
                IntParam,
                description="Sampler PGIA gain (0, 1, 2 or 3)",
                default=0,
                min=0,
                max=3,
            )
            self.sampler_channel_gain: IntParamHandle

        self.core: Core = self.get_device("core")

        self.debug_mode = logger.isEnabledFor(logging.DEBUG)

        # %% Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {"debug_mode"}

    def host_setup(self):
        if not hasattr(self, "sampler_channel"):
            self.sampler_channel = self.sampler_channel_number.get()
        if not hasattr(self, "sampler_pgia_gain_value"):
            self.sampler_pgia_gain_value = self.sampler_channel_gain.get()

        super().host_setup()

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()
        self.core.break_realtime()

        if self.debug_mode:
            gains_mu = self.sampler_device.get_gains_mu()
            logger.info("Gains before setting were %s", gains_mu)
            self.core.break_realtime()

        self.sampler_device.init()
        self.sampler_device.set_gain_mu(
            self.sampler_channel, self.sampler_pgia_gain_value
        )

    @kernel
    def read_adc(self):
        samples = [0.0] * 8
        self.sampler_device.sample(samples)

        return samples[self.sampler_channel]


class ReadSUServoADC(ReadADC):
    """
    Reads the voltage on a SUServo input channel

    The channel to be read is passed as arguments to :meth:`.build_fragment`, e.g.::

        self.setattr_fragment(
            "ReadSUServoADC", ReadSUServoADC, my_suservo_channel
        )
    """

    def build_fragment(
        self, suservo_channel: SUServoChannel, suservo_profile_number: int = -1
    ):
        self.setattr_device("core")
        self.core: Core

        self.suservo_channel: SUServoChannel = suservo_channel
        self.suservo_profile_number = suservo_profile_number

    def host_setup(self):
        super().host_setup()

        self.suservo_channel_number: int = self.suservo_channel.servo_channel
        self.suservo_device: SUServo = self.suservo_channel.servo

        # If suservo profile was not passed, assume the AION convention that the
        # profile == the channel number
        if self.suservo_profile_number == -1:
            self.suservo_profile_number = self.suservo_channel_number

        self.suservo_has_been_setup = False

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()
        if not self.suservo_has_been_setup:
            self.core.break_realtime()
            self.suservo_device.init()
            self.suservo_device.set_config(enable=1)
            self.suservo_has_been_setup = True

    @kernel
    def read_adc(self):
        return self.suservo_device.get_adc(self.suservo_channel_number)

    @kernel
    def read_ctrl_signal(self):
        return self.suservo_channel.get_y(self.suservo_profile_number)
