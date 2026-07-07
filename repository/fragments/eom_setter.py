import logging

from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.almazny import AlmaznyChannel
from artiq.coredevice.core import Core
from artiq.experiment import TFloat, delay, kernel
from artiq.language.units import ms, us
from ndscan.experiment import Fragment
from repository.models import Eom

logger = logging.getLogger(__name__)


class EomFrag(Fragment):
    """
    Set an EOM controlled by an almazny mezzanine.

    The channel to be set should be passed as an argument to
    :meth:`.build_fragment`, e.g.::

        self.setattr_fragment(
            "eom_setter",
            EomFrag,
            Eom["repump"],
            init=False,
        )
    """

    def build_fragment(self, config: Eom, init: bool = True):
        self.setattr_device("core")
        self.core: Core

        self.config: Eom = config
        self.default_freq = config.frequency
        self.default_att = config.attenuation

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
            self.set_to_defaults()

            self.first_run = False

        self.device_setup_subfragments()

    @kernel
    def set_to_defaults(self):
        """
        Set the EOM to its default state. This is called by the
        `device_setup` method if init=True.

        Advances the timeline by a small chunk ~10us
        """
        self.channel.set_att(self.config.attenuation)
        delay(2 * us)
        self.set_freq(self.config.frequency)
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

        NB: This is the frequency seen on the Almazny
        106.25 MHz <= f <= 13,600 MHz

        This uses quite a while (~400us) as it relocks the PLL
        """
        self.channel.set_frequency(frequency / 2.0)

    @kernel
    def set_att(self, attenuation: TFloat, almazny_on: bool = True):
        """
        Set the attenuation of the EOM in dB
        Also enables the Almazny channel if `almazny_on` is True

        Does not advance the timeline
        """
        self.channel.set_att(attenuation)
        self.almazny.set(
            attenuation,
            almazny_on,
            almazny_on,
        )

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
