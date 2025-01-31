import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.fastino import Fastino
from artiq.experiment import TFloat
from artiq.experiment import TInt32
from artiq.experiment import TList
from artiq.experiment import delay_mu
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import portable
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

        self.current_configs = current_configs
        self.current_configs: list[VDrivenSupply]

        assert all(
            [c.fastino == self.current_configs[0].fastino for c in self.current_configs]
        ), "All current drivers must use the same Fastino"

        self.fastino = self.get_device(self.current_configs[0].fastino)
        self.fastino: Fastino

        self.fastino_channels = [c.ch for c in self.current_configs]

        # %% Kernel variables
        self.first_run = init
        self.debug_enabled = logger.isEnabledFor(logging.DEBUG)
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

        if False:
            logger.debug(
                "Setting currents = %s with voltages = %s on channels %s",
                currents,
                voltages,
                self.fastino_channels,
            )

        for idx in range(len(self.fastino_channels)):
            self.fastino.set_dac(self.fastino_channels[idx], voltages[idx])

    def set_defaults(self):
        self.set_currents([dev.default_current for dev in self.current_configs])

    def turn_off(self):
        self.set_currents([0.0] * len(self.current_configs))

    @kernel
    def set_currents_ramping(
        self,
        currents_start: TList(TFloat),
        currents_end: TList(TFloat),
        duration: TFloat,
        ramp_step: TFloat = 1 / 75e3,
    ):
        """
        Queue a linear ramp of the currents controlled by this object

        This method will write lots of RTIO events for the `duration` of the
        ramp and will advance the timeline until the end of the ramp. It will
        also require quite a lot of time to compute and queue the ramp, so users
        should consider DMA if performance is limiting.

        Note that `time_step` will be approximate - this method will ensure that
        initial and final writes occurs at the start and end of the `duration`
        period, with `time_step` varied slightly to ensure that. Note also that
        this means you cannot immediately start a new ramp when the old one ends
        - it must be spaced at least one Fastino write away
        (`1.5us + 808ns * len(currents)` at time of writing).

        Args:
            currents_start (TList): List of starting currents / A

            currents_end (TList): List of ending currents / A

            duration (TFloat): Time to perform the ramp for

            ramp_step (TFloat, optional):
                Timestamp of RTIO writes / s. Defaults to `1/75e3` since the
                Fastino has a 75 kHz low-pass filter.
        """

        if self.debug_enabled:
            logger.info("Starting ramp for %.3f ms", 1e3 * duration)

        # Compute grid for writes
        num_points = 1 + int(duration // ramp_step)
        actual_time_step_mu = self.core.seconds_to_mu(duration / float(num_points))

        current_steps = [0.0] * self.num_supplies
        for i_supply in range(self.num_supplies):
            current_steps[i_supply] = (
                currents_end[i_supply] - currents_start[i_supply]
            ) / float(num_points - 1)

        # Here we convert the current steps to voltage steps. This assumes that
        # the current to voltage conversion function _currents_to_volts is
        # linear. If this is not true, this will break. This is tested in
        # `test_current_to_volts_convertion_is_linear`. Note that we don't
        # calculate the voltage steps in machine units. That would be vulnerable
        # to rounding errors. This means that we have to call the fastino's
        # "voltage_to_mu" function for each write which is wasteful, but assures
        # that we actually get the currents we expect.
        voltage_steps = [0.0] * self.num_supplies
        for i_supply in range(self.num_supplies):
            voltage_steps[i_supply] = self._single_current_to_volts(
                current_steps[i_supply], i_supply
            )

        # Calculate the starting voltages
        voltages_now = [0.0] * self.num_supplies
        for i_supply in range(self.num_supplies):
            voltages_now[i_supply] = self._single_current_to_volts(
                currents_start[i_supply], i_supply
            )

        if self.debug_enabled:
            logger.info(
                "Precomputation completed: %d points with steps of %s A = %s V",
                num_points,
                current_steps,
                voltage_steps,
            )

        # Queue the points, including an initial and final point
        for _ in range(num_points):
            # Set voltages
            self.fastino.set_group(self.fastino_channels, voltages_now)

            # Calculate next voltages
            for i_supply in range(self.num_supplies):
                voltages_now[i_supply] += voltage_steps[i_supply]

            delay_mu(actual_time_step_mu)

        if self.debug_enabled:
            logger.info("RTIO events queued - now_mu() = %d", now_mu())
