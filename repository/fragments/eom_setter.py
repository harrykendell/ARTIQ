import logging

from artiq.coredevice.core import Core
from artiq.coredevice.almazny import AlmaznyChannel
from artiq.coredevice.adf5356 import ADF5356
from artiq.language.units import us, ms
from artiq.experiment import (
    TFloat,
    delay,
    kernel,
)
from ndscan.experiment import Fragment

from repository.models import Eom

logger = logging.getLogger(__name__)


class SetEOM(Fragment):
    """
    Set an EOM controlled by an almazny mezzanine.
    """

    def build_fragment(self, config: Eom, init: bool = True):
        self.setattr_device("core")
        self.core: Core

        self.config: Eom = config

        self.channel = self.get_device(self.config.mirny_ch)
        self.channel: ADF5356

        self.almazny = self.get_device(self.config.almazny_ch)
        self.almazny: AlmaznyChannel

        # Kernel variables
        self.first_run = init
        self.debug_enabled = logger.isEnabledFor(logging.INFO)

        # Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "debug_enabled",
            "channel",
            "almazny",
        }

    @kernel
    def device_setup(self) -> None:
        if self.first_run:
            # set to defaults if we want to initialise
            if self.debug_enabled:
                logger.info(
                    "Initiating Mirny %s + Almazny %s", self.channel, self.almazny
                )

            self.core.break_realtime()
            self.channel.cpld.init()

            self.core.break_realtime()
            self.set_defaults()

            self.first_run = False

        self.device_setup_subfragments()

    @kernel
    def set_defaults(self):
        """
        Set the EOM to its default state. This is called by the
        `device_setup` method it init=True.

        Advances the timeline by a small chunk ~10us
        """
        self.channel.set_att(self.config.attenuation)
        delay(2 * us)
        self.channel.set_frequency(self.config.frequency)
        delay(2 * us)
        if self.config.mirny_enabled:
            self.channel.sw.on()
        else:
            self.channel.sw.off()
        delay(2 * us)

        self.almazny.set(
            self.config.attenuation,
            self.config.almazny_enabled,
            self.config.almazny_enabled,
        )

    @kernel
    def enable(self):
        """
        Enable the Almazny channel

        Does not advance the timeline
        """
        self.almazny.set(
            self.config.attenuation,
            True,
            True,
        )

    @kernel
    def disable(self):
        """
        Disable the Almazny channel

        Does not advance the timeline
        """
        self.almazny.set(
            self.config.attenuation,
            False,
            False,
        )

    @kernel
    def set_freq(self, frequency: TFloat):
        """
        Set the frequency of the EOM in MHz
        53.125 MHz <= f <= 6800 MHz

        Does not advance the timeline
        """
        self.channel.set_frequency(frequency)

    @kernel
    def set_att(self, attenuation: TFloat):
        """
        Set the attenuation of the EOM in dB

        Does not advance the timeline
        """
        self.channel.set_att(attenuation)

    @kernel
    def pulse(self, on_duration=20 * ms, off_duration=1 * ms):
        """
        Pulse the Almazny channel for a given duration on/off
        """
        self.enable()
        delay(on_duration)
        self.disable()
        delay(off_duration)

    @kernel
    def pulse_off(self, on_duration=20 * ms, off_duration=1 * ms):
        """
        Pulse the Almazny channel for a given duration on/off
        """
        self.disable()
        delay(off_duration)
        self.enable()
        delay(on_duration)
