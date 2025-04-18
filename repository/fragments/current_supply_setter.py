import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.fastino import Fastino
from artiq.experiment import (
    TFloat,
    TInt32,
    TList,
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
        self.set_currents_ramping_numpoints(
            currents_start, currents_end, duration, 1 + int(duration // ramp_step)
        )

    @kernel
    def actual_timestep_mu(self, duration: TFloat, num_points: TInt32):
        return self.core.seconds_to_mu(duration / float(num_points))

    @kernel
    def set_currents_ramping_numpoints(
        self,
        currents_start: TList(TFloat),
        currents_end: TList(TFloat),
        duration: TFloat,
        num_points: TInt32 = 1000,
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

            num_points (TInt32, optional): Number of samples
        """
        if self.debug_enabled:
            slack_mu = now_mu() - self.core.get_rtio_counter_mu()
            logger.info("Starting ramp for %.3f ms", 1e3 * duration)
            at_mu(self.core.get_rtio_counter_mu() + slack_mu)

        # Compute grid for writes
        actual_time_step_mu = self.actual_timestep_mu(duration, num_points)

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
            slack_mu = now_mu() - self.core.get_rtio_counter_mu()
            logger.info(
                "Precomputation completed: %d points with steps of %s A = %s V",
                num_points,
                current_steps,
                voltage_steps,
            )
            at_mu(self.core.get_rtio_counter_mu() + slack_mu)

        # Queue the points, including an initial and final point
        for _ in range(num_points):
            # Set voltages and calculate next voltages
            for i_supply in range(self.num_supplies):
                self.fastino.set_dac(
                    self.fastino_channels[i_supply], voltages_now[i_supply]
                )
                voltages_now[i_supply] += voltage_steps[i_supply]

            delay_mu(actual_time_step_mu)

        if self.debug_enabled:
            slack_mu = now_mu() - self.core.get_rtio_counter_mu()
            logger.info("RTIO events queued - now_mu() = %d", now_mu())
            at_mu(self.core.get_rtio_counter_mu() + slack_mu)

    @kernel
    def smooth_voltage_ramp(
        self,
        dac_channel,
        start_v=1.0,
        end_v=2.0,
        duration=20 * ms,
        max_step_duration=20 * ms,
        steps=None,
    ):
        """Create a voltage ramp of arbitrary duration with smooth transitions.

        This function combines CIC interpolation with timeline-based programming to
        create smooth voltage transitions of any duration.

        Args:
            dac_channel: DAC channel number (0-31)
            start_v: Starting voltage in volts
            end_v: Ending voltage in volts
            duration: Total ramp duration
            max_step_duration: Maximum duration for a single CIC interpolation step
            steps: Optional number of steps to use (overrides max_step_duration)
        """
        # Calculate how many steps we need
        if steps is None:
            # Each CIC interpolation can handle up to ~25ms
            # Using 80% of theoretical max for safety margin
            num_steps = int(duration / (max_step_duration * 0.8)) + 1
        else:
            num_steps = steps

        step_time = duration / num_steps
        voltage_step = (end_v - start_v) / num_steps

        # Configure the CIC interpolator for each step
        # Calculate appropriate interpolation rate based on step_time
        frames_per_step = step_time / self.core.mu_to_seconds(self.t_frame)

        # Select a reasonable rate that's below the maximum (65536)
        # but still provides good smoothness
        rate = min(int(frames_per_step / 4), 65530)
        if rate < 2:
            rate = 2  # Ensure at least some interpolation

        # Setup the CIC interpolator
        self.stage_cic(rate)

        # Enable continuous updates on this channel
        self.set_continuous(1 << dac_channel)

        # Apply the interpolator setting to the channel
        self.apply_cic(1 << dac_channel)

        # Wait for interpolator to stabilize
        delay_mu(4 * self.t_frame)

        # Set initial voltage
        self.set_dac(dac_channel, start_v)
        delay_mu(4 * self.t_frame)

        # Record start time for precise timeline control
        t_start = now_mu()

        # For very short durations, just do a single CIC interpolation
        if num_steps == 1:
            self.set_dac(dac_channel, end_v)
            # Wait for completion
            at_mu(t_start + self.core.seconds_to_mu(duration))
            return

        # For longer durations, schedule each step with precise timing
        for i in range(1, num_steps + 1):
            step_voltage = start_v + i * voltage_step
            # Schedule this voltage update at the precise time
            at_mu(t_start + self.core.seconds_to_mu(i * step_time))
            self.set_dac(dac_channel, step_voltage)
