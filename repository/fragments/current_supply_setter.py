import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.fastino import Fastino
from artiq.experiment import (
    TFloat,
    TInt32,
    TList,
    delay,
    delay_mu,
    kernel,
    now_mu,
    at_mu,
    portable,
)
from artiq.language.units import ms
from ndscan.experiment import Fragment

from repository.models import VDrivenSupply

logger = logging.getLogger(__name__)


class SetAnalogCurrentSupplies(Fragment):
    """
    Set multiple current supplies that are controlled by a analog voltages.
    The supplies must all be controlled by the same fastino
    """

    def build_fragment(self, current_configs: List[VDrivenSupply], init: bool = True):
        self.setattr_device("core")
        self.core: Core

        self.current_configs: list[VDrivenSupply] = current_configs

        assert all(
            [c.fastino == self.current_configs[0].fastino for c in self.current_configs]
        ), "All current drivers must use the same Fastino"

        self.fastino = self.get_device(self.current_configs[0].fastino)
        self.fastino: Fastino

        self.fastino_channels = [c.ch for c in self.current_configs]

        # %% Kernel variables
        self.first_run = init
        self.debug_enabled = logger.isEnabledFor(logging.INFO)
        self.num_supplies = len(self.current_configs)

        # %% Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "debug_enabled",
            "num_supplies",
            "current_configs",
            "fastino",
            "fastino_channels",
        }

    @kernel
    def device_setup(self) -> None:
        if self.first_run:
            if self.debug_enabled:
                logger.info("Initiating Fastino %s", self.fastino)

            self.core.break_realtime()
            self.fastino.init()
            self.fastino.set_continuous(
                0xFFFFFFFF  # set continous bitmask for all 32 channels
            )

            self.first_run = False

        self.device_setup_subfragments()

    @portable
    def _single_current_to_volts(self, current: TFloat, current_supply_idx: TInt32):
        lim = self.current_configs[current_supply_idx].current_limit
        gain = self.current_configs[current_supply_idx].gain
        return min(lim, current / gain)

    @portable
    def _currents_to_volts(self, currents: TList(TFloat), voltages_out: TList(TFloat)):
        if len(currents) != len(self.current_configs):
            raise ValueError("Wrong number of currents")

        if len(currents) != len(voltages_out):
            raise ValueError("Output array is wrong size")

        for i in range(len(self.current_configs)):
            voltages_out[i] = self._single_current_to_volts(currents[i], i)

    @kernel
    def set_currents(self, currents: TList(TFloat)):
        """
        Set currents in amps.

        This method does not advance the timeline but does require at least
        1.5us + 808ns * len(currents) on a Kasli 1.x as SPI events are written
        into the past.
        """
        voltages = [0.0] * len(self.current_configs)

        self._currents_to_volts(currents, voltages)

        if self.debug_enabled:
            slack_mu = now_mu() - self.core.get_rtio_counter_mu()
            logger.info(
                "Setting currents = %s via voltages = %s on channels %s",
                currents,
                voltages,
                self.fastino_channels,
            )
            at_mu(self.core.get_rtio_counter_mu() + slack_mu)

        for idx in range(len(self.fastino_channels)):
            self.fastino.set_dac(self.fastino_channels[idx], voltages[idx])
            delay_mu(
                8
            )  # Nothing happens for multiple channels if we use a shorter delay?!

    @kernel
    def set_defaults(self):
        self.set_currents([dev.default_current for dev in self.current_configs])

    @kernel
    def turn_off(self):
        self.set_currents([0.0] * len(self.current_configs))

    @kernel
    def set_currents_ramping(
        self,
        currents_start: TList(TFloat),
        currents_end: TList(TFloat),
        duration: TFloat,
        num_steps: TInt32 = 100,
    ):
        """
        Queue a linear ramp of the currents controlled by this object

        This method will write lots of RTIO events for the `duration` of the
        ramp and will advance the timeline until the end of the ramp. It will
        also require quite a lot of time to compute and queue the ramp, so users
        should consider DMA if performance is limiting.

        Args:
            currents_start (TList): List of starting currents / A

            currents_end (TList): List of ending currents / A

            duration (TFloat): Time to perform the ramp for
        """
        # work out voltages from currents
        start_voltages = [0.0] * self.num_supplies
        end_voltages = [0.0] * self.num_supplies
        for i_supply in range(self.num_supplies):
            start_voltages[i_supply] = self._single_current_to_volts(
                currents_start[i_supply], i_supply
            )
            end_voltages[i_supply] = self._single_current_to_volts(
                currents_end[i_supply], i_supply
            )
        if self.debug_enabled:
            slack_mu = now_mu() - self.core.get_rtio_counter_mu()
            logger.info(
                "Starting ramp for %.3f ms",
                1e3 * duration,
            )
            at_mu(self.core.get_rtio_counter_mu() + slack_mu)

        # work out time steps - we want to avoid collisions so space each supplies' write by t_frame
        # this means we need at least t_frame * num_supplies per timestep or they collide again
        t_frame = self.core.mu_to_seconds(self.fastino.t_frame)
        time_step = duration / num_steps 
        if time_step < (t_frame * self.num_supplies): # avoid collisions
            time_step = t_frame / self.num_supplies
            num_steps = max(1, int(duration / time_step))
            logger.error("Requested steps occur too fast. Decreased steps to %d", num_steps)
        time_per_step = self.core.seconds_to_mu(time_step)

        # Do the ramping
        start_of_ramp = now_mu()
        for i in range(num_steps):
            for i_supply in range(self.num_supplies):
                self.fastino.set_dac(
                    self.fastino_channels[i_supply],
                    start_voltages[i_supply]
                    + (end_voltages[i_supply] - start_voltages[i_supply])
                    * i
                    / num_steps,
                )
                delay_mu(self.fastino.t_frame)
            at_mu(start_of_ramp + time_per_step * (i+1))

        # Set the final voltages
        for i_supply in range(self.num_supplies):
            self.fastino.set_dac(
                self.fastino_channels[i_supply], end_voltages[i_supply]
            )
            delay_mu(self.fastino.t_frame)
