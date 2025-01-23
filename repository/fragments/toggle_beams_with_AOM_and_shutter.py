import logging
from typing import List

import numpy as np
from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.ttl import TTLOut
from artiq.experiment import at_mu
from artiq.experiment import delay
from artiq.experiment import delay_mu
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import portable
from ndscan.experiment import Fragment

from repository.utils import get_local_devices
from repository.utils.models import SUServoedBeam


logger = logging.getLogger(__name__)


class ControlBeamsWithoutCoolingAOM(Fragment):
    """
    Methods to turn on/off a list of beams using a SUServoed AOM for sharp edges
    and a shutter to fully block it

    The AOMs will be left on as much as possible even while the beams are off
    (but blocked with the shutter) to avoid pointing instability from thermal
    effects.

    Note that when groups of beams are intended to be turned on together, you
    should use a single instance of this fragment to control all of them rather
    than initialising one for each beam. That's because this fragment skips
    forwards and backwards in time and will therefore wantonly consume RTIO
    lanes unless you let it reduce this behaviour by knowing in advance which
    shutters need to be opened.

    Note that the beam turn-on/off events will not quite be simultaneous, but
    will actually be separated by 8ns. This is so that only one RTIO lane is
    consumed, avoiding collisions. If this is unacceptable for your application,
    you will need to manage the lane usage manually.

    Example usage
    -------------

    This example just turns on and off one beam, but you could (and should) pass
    several. This is a :class:`~ndscan.experiment.fragment.Fragment` and so needs to be called from another
    fragment.::

        from ndscan.experiment import *

        from pyaion.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
        from pyaion.models import SUServoedBeam


        my_beam = SUServoedBeam(
            name="my_blue_beam_for_physics_stuff",
            frequency="150e6",
            attenuation=20,
            suservo_device="suservo_aom_singlepass_461_2DMOT_A",
            shutter_device="ttl_shutter_461_2DMOT_A",
            shutter_delay=20e-3,
        )


        class MyBeamTurnerOnnererFrag(ExpFragment):
            def build_fragment(self):
                self.setattr_device("core")

                self.setattr_fragment(
                    "my_beam_setter",
                    ControlBeamsWithoutCoolingAOM,
                    beam_infos=[my_beam],
                )
                self.my_beam_setter: ControlBeamsWithoutCoolingAOM

            @kernel
            def turn_on_the_beam(self):
                self.core.break_realtime()
                self.my_beam_setter.turn_beams_on()

            @kernel
            def turn_off_the_beam(self):
                self.core.break_realtime()
                self.my_beam_setter.turn_beams_off()

            @kernel
            def run_once(self) -> None:
                self.turn_on_the_beam()
                delay(1.0)
                self.turn_off_the_beam()


        MyBeamTurnerOnnerer = make_fragment_scan_exp(MyBeamTurnerOnnererFrag)
    """

    def build_fragment(self, beam_infos: List[SUServoedBeam]):
        self.setattr_device("core")
        self.core: Core

        self.beam_suservos: List[SUServoChannel] = []
        self.beam_shutters: List[TTLOut] = []

        # Sort beams by order of delay - smallest delay first
        self.beam_infos = sorted(beam_infos, key=lambda v: v.shutter_delay)

        # Add a dummy entry to the list. This is so that the ARTIQ compiler can
        # infer the type even if we're passed an empty list. We'll ignore these
        # in the loops
        dummy_beaminfo = SUServoedBeam(
            name="dummy",
            frequency=0,
            attenuation=0.0,
            shutter_device=get_local_devices(self, TTLOut)[0],
            suservo_device=get_local_devices(self, SUServoChannel)[0],
            shutter_delay=0,
        )
        self.beam_infos.insert(0, dummy_beaminfo)

        for beam_info in self.beam_infos:
            if beam_info.shutter_device is None:
                raise ValueError(
                    "Beam [{:s}] has no shutter configured".format(beam_info.name)
                )

            self.beam_suservos.append(self.get_device(beam_info.suservo_device))
            self.beam_shutters.append(self.get_device(beam_info.shutter_device))

        self.longest_beam_delay = max([info.shutter_delay for info in self.beam_infos])

        # %% Kernel variables
        self.debug_enabled = logger.isEnabledFor(logging.DEBUG)

        # %% Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "debug_enabled",
            "longest_beam_delay",
        }

    def host_setup(self):
        # This is one coarse cycle time, the minimum time delay if you want to
        # avoid using an extra RTIO lane
        self.t_rtio_cycle_mu = np.int64(self.core.ref_multiplier)
        self.kernel_invariants.add("t_rtio_cycle_mu")

        return super().host_setup()

    @kernel
    def turn_beams_on(self, ignore_shutters=False):
        """
        Turn on the beams using the AOM and shutter

        This method will use the AOM to turn on the beam at the cursor, having
        first disabled the AOM and opened the shutter to prevent the AOM from
        cooling down too much.

        Start with the shutters with the longest delay to avoid switching
        backwards and forwards in time.

        This method advances the timeline cursor by a few RTIO events ~ 100ns

        If ignore_shutters == True, only the AOMs are used. The user is
        responsible for making sure that the shutters are arranged such that
        this results in something interesting happening.

        Event queueing behaviour:

        * t < 0: If ignore_shutters == False and there are shutterable AOMs in
        the suservo list, this method will write shutter opening events in the
        past by "shutter_delay_time" seconds.
        * t > 0: No events are written in the future.
        """

        if not ignore_shutters:
            for i in range(len(self.beam_infos) - 1, 0, -1):
                suservo = self.beam_suservos[i]
                shutter = self.beam_shutters[i]
                beam_info = self.beam_infos[i]

                delay(-beam_info.shutter_delay)

                suservo.set(
                    en_out=0,
                    en_iir=0,
                    profile=suservo.channel,
                )
                delay_mu(self.t_rtio_cycle_mu)
                shutter.on()
                delay_mu(self.t_rtio_cycle_mu)

                delay(beam_info.shutter_delay)

        for i in range(len(self.beam_infos) - 1, 0, -1):
            suservo = self.beam_suservos[i]
            shutter = self.beam_shutters[i]
            beam_info = self.beam_infos[i]

            if self.debug_enabled:
                slack_mu = now_mu() - self.core.get_rtio_counter_mu()
                logger.info(
                    (
                        "AOM+shuttering ON: "
                        "suservo = 0x%x, "
                        "shutter = 0x%x, "
                        "delay_by = %s, "
                        "servo_enabled = %s, "
                        "info = %s"
                    ),
                    suservo.channel,
                    shutter.channel,
                    beam_info.shutter_delay,
                    beam_info.servo_enabled,
                    beam_info,
                )
                at_mu(self.core.get_rtio_counter_mu() + slack_mu)

            suservo.set(
                en_out=1,
                en_iir=1 if beam_info.servo_enabled else 0,
                profile=suservo.channel,
            )

            delay_mu(self.t_rtio_cycle_mu)

    @kernel
    def turn_beams_off(self, ignore_shutters=False):
        """
        Turn off the beams using the AOM and shutter

        This method will turn off the beam at the cursor and then close the
        shutter and turn the AOM back on to stop it cooling down.

        This method advances the timeline cursor by a few RTIO events ~ 100ns

        If ignore_shutters == True, only the AOMs are used. The user is
        responsible for making sure that the shutters are arranged such that
        this results in something interesting happening.

        Event queueing behaviour:

        * t < 0: No events are written in the past.
        * t > 0: If ignore_shutters == False and there are shutterable AOMs in
        the suservo list, this method will write shutter closing
        events into the future by "shutter_delay_time" seconds.
        """

        for i in range(1, len(self.beam_infos)):
            suservo = self.beam_suservos[i]
            shutter = self.beam_shutters[i]

            suservo.set(
                en_out=0,
                en_iir=0,
                profile=suservo.channel,
            )

            # TODO: Not having the below delay DOES cause this method to consume
            # an extra lane, but fixing this caused overflow bugs in our code so
            # I'm removing it here in case others have the same problem.
            # delay_mu(self.t_rtio_cycle_mu)

            if not ignore_shutters:
                shutter.off()
                delay_mu(self.t_rtio_cycle_mu)

        if not ignore_shutters:
            for i in range(1, len(self.beam_infos)):
                suservo = self.beam_suservos[i]
                shutter = self.beam_shutters[i]
                beam_info = self.beam_infos[i]

                delay(beam_info.shutter_delay)

                # If the servo was engaged, this should recall the last output value:
                suservo.set(
                    en_out=1,
                    en_iir=0,
                    profile=suservo.channel,
                )

                delay_mu(self.t_rtio_cycle_mu)

                delay(-beam_info.shutter_delay)

    @portable
    def get_longest_shutter_delay(self):
        return self.longest_beam_delay
