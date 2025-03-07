import logging
from typing import Set

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel
from artiq.coredevice.suservo import SUServo, T_CYCLE, COEFF_SHIFT, COEFF_WIDTH
from artiq.coredevice.urukul import CPLD
from artiq.experiment import (
    delay,
    delay_mu,
    kernel,
    rpc,
    TBool,
    TFloat,
    TInt32,
    MHz,
    ms,
)
from ndscan.experiment import Fragment
from numpy import int32

from repository.models.devices import SUSERVOED_BEAMS


class SUServoFrag(Fragment):
    """
    Set a static SUServo output

    The channel to be set should be passed as an argument to
    :meth:`.build_fragment`, e.g.::

        self.setattr_fragment(
            "SUServoFrag", SUServoFrag, "suservo0_ch0",
        )

    The :meth:`~ndscan.experiment.fragment.Fragment.device_setup` of this
    :class:`~ndscan.experiment.fragment.ExpFragment` will reinitialise the
    entire SUServo device. This Fragment then provides a :meth:`.set_suservo`
    method which can be used to set the specified channel's output.

    Unfortunately, it's not possible to read out the attenuation register from
    an Urukul in SUServo mode (see
    https://github.com/quartiq/urukul/blob/af67d56c0158d61d0232a491cf123a5e6767ecbf/urukul.py#L254-L282).
    This class must therefore reset the attenuations of all channels when it
    changes the attenuation of one - i.e. all SUServo outputs that share an
    Urukul with the one being written and that have not had their attenuation
    set during the current ARTIQ experiment will have their attenuations reset.
    """

    # A set of which suservos have been initiated, stored as a class variable
    # so that suservo devices are only initiated once. This is a set of ARTIQ
    # channels that represent suservos which have been initiated during this
    # EnvExperiment
    initiated_suservos: Set[int] = set()

    def build_fragment(self, channel: str):
        self.setattr_device("core")
        self.core: Core

        self.channel = channel

        # Kernel variables
        self.debug_enabled = logging.getLogger().getEffectiveLevel() >= logging.DEBUG
        self.first_run = True

        # %% Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {"debug_enabled"}

    def host_setup(self):
        super().host_setup()

        self.suservo_channel: Channel = self.get_device(self.channel)
        self.suservo: SUServo = self.suservo_channel.servo

        # We pull default settings for the other beams on this cpld to avoid clobbering their atts in set_all_attenuations
        # We assume that all suservo_chs are ordered properly by channel# so that for each set of 4 they share a cpld

        # Find the default attenuations from SUSERVOED_BEAMS
        beams = [
            (dev.name, dev.suservo_device, dev.attenuation)
            for dev in SUSERVOED_BEAMS.values()
        ]
        minch = min([self.get_device(dev[1]).channel for dev in beams])
        # Assume cplds are logically chunked by channel number
        start_ch = (self.suservo_channel.channel - minch) // 4 * 4
        # our number inside the group of 4
        self.ch_4 = (self.suservo_channel.channel - minch) % 4
        # we now want this and the next 3 channels
        self.beams = beams[start_ch : start_ch + 4]
        if self.debug_enabled:
            logging.info(
                "Default beams: %s",
                self.beams,
            )

        # These are conventions in the AION lab:
        self.sampler_channel: int = self.suservo_channel.servo_channel
        self.suservo_profile: int = self.suservo_channel.servo_channel

        self.kernel_invariants.add("suservo_channel")
        self.kernel_invariants.add("suservo")
        self.kernel_invariants.add("sampler_channel")
        self.kernel_invariants.add("suservo_profile")
        self.kernel_invariants.add("beams")

    @kernel
    def calc_atts_reg(self, att):
        # We have to write all 4 channels at once due to hardware constraints.
        # We therefore need to use the defaults for everything but ourselves
        reg = 0
        for i in range(4):
            delay(1 * ms)
            reg += self.suservo.cplds[0].att_to_mu(
                self.beams[i][2] if i != self.ch_4 else att
            ) << (i * 8)
        return reg

    @rpc
    def mark_suservo_initiated(self, suservo_channel: TInt32) -> TBool:
        """
        Check whether the given suservo has been initiated and return True if it
        has. In either case, mark it as now having been initiated

        This is an RPC so that we can use python features like class members to
        communicate between instances. This could be done purely on the core
        using e.g. a singleton class, but that's more complex. Here I'll pay the
        few ms penalty for keeping the code simpler.
        """
        out = suservo_channel in self.__class__.initiated_suservos
        self.__class__.initiated_suservos.add(suservo_channel)
        return out

    @kernel
    def device_setup(self):
        self.device_setup_subfragments()

        # Initiate the suservo itself (i.e. all four channels)
        if self.first_run and not self.mark_suservo_initiated(self.suservo.channel):
            if self.debug_enabled:
                logging.info(
                    "Initiating suservo %s = artiq channel 0x%x -> enabled",
                    self.channel,
                    self.suservo.channel,
                )

            self.core.break_realtime()
            self.suservo.init()
            self.suservo.set_config(enable=1)

        else:
            if self.debug_enabled:
                logging.info(
                    "Skipping suservo %s  - already initiated",
                    self.channel,
                )

        if self.first_run:
            self.first_run = False
            self.core.break_realtime()

            # Set the PGIA to 1x - there's no way to read it, so we have to have
            # a deterministic initialisation
            self.set_pgia_gain_mu(0)

    @kernel
    def log_channel(self, profile_num: int32 = -1):
        """
        Extract approximate real values from the mu-encoded profile

        profile_mu is
        [ftw >> 16, b1, pow, adc | (delay << 8), offset, a1, ftw & 0xffff, b0]

        returns : freq, phase, sampler_channel, delay, offset, kp, ki, gain_limit
        """
        if profile_num == -1:
            profile_num = self.suservo_profile

        buffer = [0] * 8
        self.core.break_realtime()
        self.suservo_channel.get_profile_mu(profile_num, buffer)

        self.core.break_realtime()
        freq = self.suservo_channel.dds.ftw_to_frequency((buffer[0] << 16) | buffer[6])
        self.core.break_realtime()
        phase = self.suservo_channel.dds.pow_to_turns(buffer[2])
        sampler_channel = buffer[3] & 0xFF
        delay = (buffer[3] >> 8) * T_CYCLE
        offset = buffer[4] / (1 << COEFF_WIDTH - 1)

        a1 = float(buffer[5])
        b0 = float(buffer[7])
        b1 = float(buffer[1])

        kp = 0.0
        ki = 0.0
        gain_limit = 0.0

        B_NORM = 1 << COEFF_SHIFT + 1
        A_NORM = 1 << COEFF_SHIFT

        if a1 == 0.0:  # pure P so ki=0 and gain can't be recovered
            kp = b0
        # I or PI
        elif a1 == A_NORM:  # g == 0 so get kp and ki
            kp = (b0 - b1) / 2.0
            ki = (b0 + b1) / 2.0
        else:  # g != 0 so get all three
            c = (a1 / A_NORM + 1.0) / 2.0
            kp = (b0 - b1) / 2.0 / c
            ki = (b0 - kp) / c

            gain_limit = ki / B_NORM / (1.0 / c - 1.0)

        kp /= B_NORM
        ki /= B_NORM * T_CYCLE / 2.0

        self.core.break_realtime()
        y = self.suservo_channel.get_y(profile_num)
        self.core.break_realtime()
        status = self.suservo.get_status()
        # Bit 0: enabled, bit 1: done, bits 8-15: channel clip indicators.
        logging.info("a1=%s, b0=%s, b1=%s", a1, b0, b1)
        logging.info(
            "SUServo enabled=%s,done=%s,clipping=%s",
            bool(status & 1),
            bool(status & 2),
            status >> 8,
        )
        logging.info(
            "Profile %s (y=%s): freq=%s, phase=%s, sampler_channel=%s, delay=%s, offset=%s, kp=%s, ki=%s, gain_limit=%s",
            profile_num,
            y,
            freq / MHz,
            phase,
            sampler_channel,
            delay,
            offset,
            kp,
            ki,
            gain_limit,
        )

    @kernel
    def setpoint_to_offset(self, setpoint_v: TFloat) -> TFloat:
        """Convert a setpoint in volts to a SUServo offset

        Args:
            setpoint_v (TFloat): Setpoint in volts

        Returns:
            TFloat: Offset in SUServo units
        """
        # Setpoints are stored in units of full scale, where 1.0 -> +10V, -1.0 -> -10V
        return -1.0 * setpoint_v / 10.0

    @kernel
    def set_this_attenuation(self, attenuation: TFloat):
        # Set the attenuator for this channel on this Urukul
        attenuator_channel = self.suservo_channel.servo_channel % 4

        if self.debug_enabled:
            logging.info(
                "Setting the attenuator for %s (%s/4) to %f",
                self.channel,
                attenuator_channel,
                attenuation,
            )
            self.core.break_realtime()

        cpld = self.suservo_channel.dds.cpld  # type: CPLD
        cpld.set_att(attenuator_channel, attenuation)

    @kernel
    def set_all_attenuations(self, attenuation: TFloat):
        """
        Set all channels on the same DDS as this channel to their defaults

        This is annoyingly required because there is no way of getting
        information out from the SUServo gateware about the current settings, so
        they have to be reset on each run.
        """
        logging.warning("Setting the attenuator for all channels to their defaults")

        self.core.break_realtime()
        cpld = self.suservo_channel.dds.cpld  # type: CPLD
        cpld.get_att_mu()

        cpld.set_all_att_mu(self.calc_atts_reg(attenuation))

    @kernel
    def set_suservo(
        self,
        freq: TFloat,
        amplitude: TFloat,
        attenuation: TFloat = 16.5,
        en_out: TBool = True,
        setpoint_v: TFloat = 0.0,
        enable_iir: TBool = False,
    ):
        """Set a static output on a SUServo channel

        This method advances the timeline by at least 5 servo cycles (a bit more if the
        attenuation is changed).

        Args:
            freq (TFloat): Frequency in Hz
            amplitude (TFloat): Amplitude from 0 to 1 when 1 is 100% output.
            attenuation (TFloat, optional): Attenuation on the variable attenuator. Defaults to 16.5.
            en_out (TBool, optional): State of the RF switch. Defaults to on.
            setpoint_v (TFloat, optional): SUServo setpoint. Only relevant if enable_IRR=True. Defaults to 0.0.
            enable_iir (TBool, optional): Enable the servo loop. Defaults to False.
        """
        # Set the attenuator for this channel
        self.set_this_attenuation(attenuation)

        # Configure this profile to have the requested amplitude and frequency
        self.set_y(amplitude)

        self.set_dds(
            profile=self.suservo_profile,
            offset=self.setpoint_to_offset(setpoint_v),
            frequency=freq,
        )

        # Set channel output state
        self.set_channel_state(en_out, enable_iir)

    @kernel
    def set_dds(
        self,
        frequency: TFloat,
        profile: TInt32,
        offset: TFloat,
        phase: TFloat = 0.0,
    ):
        """
        Set the DDS parameters for this channel.

        Args:
            frequency (TFloat): Frequency in Hz
            phase (TFloat): Phase in radians
            profile (TInt32): Profile number
            offset (TFloat): IIR offset (negative setpoint) in units of full scale
        """
        if self.debug_enabled:
            logging.info(
                "Setting DDS for %s (profile=%s): frequency=%s, offset=%s, phase=%s",
                self.channel,
                profile,
                frequency,
                offset,
                phase,
            )
            self.core.break_realtime()

        self.suservo_channel.set_dds(
            profile=profile,
            offset=offset,
            frequency=frequency,
            phase=phase,
        )

    @kernel
    def set_pgia_gain_mu(self, gain_mu):
        """
        Set the PGIA gain of this channel (0,1,2,3) = (1x,10x,100x,1000x)

        See :meth:`artiq.coredevice.suservo.SUServo.set_pgia_mu` for details.
        """
        if self.debug_enabled:
            logging.info(
                "Setting PGIA gain for %s: %s",
                self.sampler_channel,
                gain_mu,
            )
            self.core.break_realtime()

        self.suservo.set_pgia_mu(self.sampler_channel, gain_mu)

    @kernel
    def set_setpoint(self, new_setpoint: TFloat):
        """Set the SUServo setpoint

        Updates only the SUServo setpoint. Does not enable the SUServo / RF switch or change any other parameters.

        Args:
            new_offset (TFloat): The new offset in volts
        """
        offset = self.setpoint_to_offset(new_setpoint)

        if self.debug_enabled:
            logging.info(
                "Setting setpoint for %s (profile=%s): %s V -> %s",
                self.channel,
                self.suservo_profile,
                new_setpoint,
                offset,
            )
            self.core.break_realtime()

        self.suservo_channel.set_dds_offset(profile=self.suservo_profile, offset=offset)

    @kernel
    def set_channel_state(self, en_out: TBool, enable_iir: TBool):
        """
        Quickly enable / disable the RF switch and servo. This method does not
        advance the timeline.

        Automatically sets the profile to the AION lab convention of the channel number.
        """
        out = 1 if en_out else 0
        iir = 1 if enable_iir else 0

        if self.debug_enabled:
            logging.info(
                "Setting channel state for %s (profile=%s): en_out=%s, enable_iir=%s",
                self.channel,
                self.suservo_profile,
                out,
                iir,
            )
            self.core.break_realtime()

        self.suservo_channel.set(
            en_out=out,
            en_iir=iir,
            profile=self.suservo_profile,
        )

    @kernel
    def set_iir_params(self, kp=-1.0, ki=-200000.0, gain_limit=-200.0, delay=0.0):
        """
        Set loop filter parameters for the suservo. See ARTIQ documentation for
        details. Note all of kp,ki,gain_limit should usually be negative.
        """
        if self.debug_enabled:
            logging.info(
                "Setting iir params for %s (profile= %s): sampler_channel=%s, kp=%s, ki=%s, gain_limit=%s, delay=%s",
                self.channel,
                self.suservo_profile,
                self.sampler_channel,
                kp,
                ki,
                gain_limit,
                delay,
            )
            self.core.break_realtime()

        self.set_y(0.0)  # clear integrator
        self.suservo_channel.set_iir(
            self.suservo_profile, self.sampler_channel, kp, ki, gain_limit, delay
        )

    @kernel
    def set_y(self, amplitude: TFloat):
        """Set the amplitude of the channel"""
        if self.debug_enabled:
            logging.info(
                "Setting y for %s (profile= %s): y=%s",
                self.channel,
                self.suservo_profile,
                amplitude,
            )
            self.core.break_realtime()

        self.suservo_channel.set_y(profile=self.suservo_profile, y=amplitude)
