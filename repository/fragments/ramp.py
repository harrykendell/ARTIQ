import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.suservo import Channel as SUServoChannel, T_CYCLE as suservo_cycle
from artiq.language.core import at_mu, delay, delay_mu, now_mu
from artiq.language.units import ms, us, ns, MHz
from artiq.experiment import kernel, portable, TFloat, TInt32
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import FloatParam, FloatParamHandle
from numpy import int32, int64

from repository.models import SUServoedBeam, Eom, VDrivenSupply
from repository.fragments.eom_setter import EomFrag
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.utils.dummy_devices import (
    DummyEomFrag,
    DummySUServoChannel,
    DummySetAnalogCurrentSupplies,
)

logger = logging.getLogger(__name__)


class Ramp(Fragment):
    """
    Template fragment for a ramp in an experiment. *Needs subclassing*
        - SUServo Frequency/Setpoint
        - VDrivenSupply Output
        - Eom Amplitude/Frequency (although frequency is slow ~0.4ms per step)

    Unspecified start and end values will be set to the default values of the
    corresponding device.

    To ramp the MOT down from default and detune by -10MHz from nominal
    as well as ramp the X1 and X2 VDrivenSupply to 1.8A and 1.9A, you could use:

    class CompressionRamp(Ramp):
        duration_default = 50*ms

        suservos = [SUServoedBeam["MOT"]]
        suservo_setpoint_end = [0.5*SUServoedBeam["MOT"].setpoint]
        suservo_detuning_end = [-10*MHz]

        eoms = [Eom["repump"]]
        eom_detuning_end = [-10*MHz/2.0]

        supplies = VDrivenSupply["X1", "X2"]
        supplies_start = [1.0, 1.0]
        supplies_end = [1.8, 1.9]
    """

    time_step_default = 100 * us
    duration_default: float = None
    add_final_point = True

    suservos: List[SUServoedBeam] = None
    suservos_used = True
    suservo_setpoint_start: List[float] = None
    suservo_setpoint_end: List[float] = None
    suservo_detuning_start: List[float] = None
    suservo_detuning_end: List[float] = None

    eoms: List[Eom] = None
    eoms_used = True
    eom_detuning_start: List[float] = None
    eom_detuning_end: List[float] = None
    do_eom_detuning = False # avoid if we can as this is slow
    eom_att_start: List[float] = None
    eom_att_end: List[float] = None

    supplies: List[VDrivenSupply] = None
    supplies_used = True
    supplies_start: List[float] = None
    supplies_end: List[float] = None

    def validate(self):
        assert self.duration_default is not None

        # Validate suservos
        if self.suservos is None:
            self.suservos_used = False
            self.suservos: List[SUServoedBeam] = [
                SUServoedBeam("dummy", -1.0, -1.0, "dummy")
            ]
        assert len(self.suservos) == len(set([ss.name for ss in self.suservos]))
        # Ensure non-empty lists are properly initialized
        if not self.suservo_detuning_start:
            self.suservo_detuning_start = [0.0 * MHz] * len(self.suservos)
        if not self.suservo_detuning_end:
            self.suservo_detuning_end = [0.0 * MHz] * len(self.suservos)
        if not self.suservo_setpoint_start:
            self.suservo_setpoint_start = [ss.setpoint for ss in self.suservos]
        if not self.suservo_setpoint_end:
            self.suservo_setpoint_end = [ss.setpoint for ss in self.suservos]

        # Validate eoms
        if self.eoms is None:
            self.eoms_used = False
            self.eoms: List[Eom] = [Eom("dummy", -1.0, -1.0, "dummy", "dummy")]
        assert len(self.eoms) == len(set([eom.name for eom in self.eoms]))
        # Ensure non-empty lists are properly initialized
        if self.eom_detuning_end or self.eom_detuning_start:
            self.do_eom_detuning = self.eoms_used
        if not self.eom_detuning_start:
            self.eom_detuning_start = [0.0 * MHz] * len(self.eoms)
        if not self.eom_detuning_end:
            self.eom_detuning_end = [0.0 * MHz] * len(self.eoms)
        if self.eom_att_end or self.eom_att_start:
            self.do_eom_att = self.eoms_used
        if not self.eom_att_start:
            self.eom_att_start = [eom.attenuation for eom in self.eoms]
        if not self.eom_att_end:
            self.eom_att_end = [eom.attenuation for eom in self.eoms]

        # Validate supplies
        if self.supplies is None:
            self.supplies_used = False
            self.supplies: List[VDrivenSupply] = [VDrivenSupply("dummy", "dummy", -1.0)]
        assert len(self.supplies) == len(set([supply.name for supply in self.supplies]))
        if not self.supplies_start:
            self.supplies_start = [supply.default_current for supply in self.supplies]
        if not self.supplies_end:
            self.supplies_end = [supply.default_current for supply in self.supplies]

    def build_fragment(self):
        self.validate()
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        self.debug_enabled = logger.isEnabledFor(logging.INFO)
        self.dma_handle = (int32(0), int64(0), int32(0), False)
        self.dma_handle_valid = False

        self.setattr_param(
            "duration",
            FloatParam,
            "Duration of phase",
            default=self.duration_default,
            min=0.0,
            unit="ms",
        )
        self.duration: FloatParamHandle

        self.setattr_param(
            "time_step",
            FloatParam,
            "Gap between steps",
            default=self.time_step_default,
            min=0.0,
            unit="us",
        )
        self.time_step: FloatParamHandle

        self.suservo_setters: List[SUServoChannel] = (
            [self.get_device(ss.suservo_device) for ss in self.suservos]
            if self.suservos_used
            else [DummySUServoChannel()]
        )

        self.eom_setters: List[EomFrag] = (
            [
                self.setattr_fragment(
                    eom.name,
                    EomFrag,
                    eom,
                    init=False,
                )
                for eom in self.eoms
            ]
            if self.eoms_used
            else [DummyEomFrag()]
        )

        # This is designed to control multiple supplies at once anyway
        # assuming they share a fastino and we only have 1
        self.supply_setter: SetAnalogCurrentSupplies = (
            self.setattr_fragment(
                "supply_setter", SetAnalogCurrentSupplies, self.supplies, init=False
            )
            if self.supplies_used
            else DummySetAnalogCurrentSupplies()
        )

    @kernel
    def device_setup(self):
        """
        Records the ramps to DMA.

        Write events are staggered by 8 ns (self.core.ref_multiplier) to use
        only one lane.
        """
        self.device_setup_subfragments()

        # Compute grid for writes. See comments in docstring regarding how the
        # ramp is played / ends - it's easy to introduce an off-by-one error
        # unless you're really careful
        num_points = int(self.duration.get() // self.time_step.get()) + 1

        # Always have at least two points, although the final one won't get
        # written unless add_final_point is set
        if num_points <= 1:
            num_points = 2

        # Calculate the time step in machine units
        time_step = self.duration.get() / float(num_points - 1)
        time_step_mu = self.core.seconds_to_mu(time_step)

        # Compute step sizes and initial values
        supply_values = [0.0] * len(self.supplies)
        supply_steps = [0.0] * len(self.supplies)
        if self.supplies_used:  # only run the calculations if needed
            for i in range(len(self.supplies)):
                supply_values[i] = self.supplies_start[i]
                supply_steps[i] = self._calc_step_size(
                    self.supplies_start[i], self.supplies_end[i], num_points
                )

        eom_att_values = [0.0] * len(self.eoms)
        eom_freq_values = [0.0] * len(self.eoms)
        eom_att_steps = [0.0] * len(self.eoms)
        eom_freq_steps = [0.0] * len(self.eoms)
        if self.eoms_used:  # only run the calculations if needed
            for i in range(len(self.eoms)):
                eom_att_values[i] = self.eom_att_start[i]
                eom_freq_values[i] = self.eoms[i].frequency + self.eom_detuning_start[i]
                eom_att_steps[i] = self._calc_step_size(
                    self.eom_att_start[i], self.eom_att_end[i], num_points
                )
                eom_freq_steps[i] = self._calc_step_size(
                    self.eom_detuning_start[i], self.eom_detuning_end[i], num_points
                )

        suservo_freq_values = [0.0] * len(self.suservos)
        suservo_setpoint_values = [0.0] * len(self.suservos)
        suservo_freq_steps = [0.0] * len(self.suservos)
        suservo_setpoint_steps = [0.0] * len(self.suservos)
        if self.suservos_used:  # only run the calculations if needed
            for i in range(len(self.suservos)):
                suservo_freq_values[i] = (
                    self.suservos[i].frequency + self.suservo_detuning_start[i]
                )
                suservo_setpoint_values[i] = self.suservo_setpoint_start[i]
                suservo_freq_steps[i] = self._calc_step_size(
                    self.suservo_detuning_start[i],
                    self.suservo_detuning_end[i],
                    num_points,
                )
                suservo_setpoint_steps[i] = self._calc_step_size(
                    self.suservo_setpoint_start[i],
                    self.suservo_setpoint_end[i],
                    num_points,
                )

        if self.debug_enabled:
            logger.info("Ramping %s", self.fqn)
            logger.info("%s ms in %s steps", self.duration.get() / ms, num_points)
            if self.supplies_used:
                logger.info("Supplies from %s by %s", supply_values, supply_steps)
            if self.eoms_used:
                logger.info(
                    "EOMs from %s / %s by %s / %s",
                    eom_freq_values,
                    eom_att_values,
                    eom_freq_steps,
                    eom_att_steps,
                )
                logging.error("Verify this is changing the almazny not just the mirny att.")
            if self.suservos_used:
                logger.info(
                    "SUServos from %s / %s by %s / %s",
                    suservo_freq_values,
                    suservo_setpoint_values,
                    suservo_freq_steps,
                    suservo_setpoint_steps,
                )

        # Record these ramping parameters into a DMA sequence
        with self.core_dma.record(self.fqn):
            t_start_sequence_mu = now_mu()
            t_start_this_step_mu = now_mu()
            t_one_rtio_cycle_mu = int64(self.core.ref_multiplier)
            num_points_for_loop = num_points if self.add_final_point else num_points - 1

            # Play the ramp
            for i_step in range(num_points_for_loop):
                # First the Fastino as it writes into the past
                if self.supplies_used:
                    self.supply_setter.set_currents(supply_values)
                    for i in range(len(supply_values)):
                        supply_values[i] += supply_steps[i]

                delay_mu(14 * 7 * 4)  # Avoid using multiple lanes

                # SUServos next
                if self.suservos_used:
                    for i in range(len(self.suservos)):
                        self.suservo_setters[i].set_dds(
                            self.suservo_setters[i].servo_channel,
                            suservo_freq_values[i],
                            -1.0 * suservo_setpoint_values[i] / 10.0,
                        )
                        suservo_freq_values[i] += suservo_freq_steps[i]
                        suservo_setpoint_values[i] += suservo_setpoint_steps[i]

                        delay_mu(t_one_rtio_cycle_mu)

                # EOMs last
                if self.eoms_used:
                    for i in range(len(self.eoms)):
                        self.eom_setters[i].set_att(eom_att_values[i])
                        eom_att_values[i] += eom_att_steps[i]
                        delay_mu(t_one_rtio_cycle_mu)
                        # freq for mirny is very slow so only set 1/10 of the time
                        if self.do_eom_detuning:
                            self.eom_setters[i].set_freq(eom_freq_values[i])
                        eom_freq_values[i] += eom_freq_steps[i]

                t_total_used_mu = now_mu() - t_start_sequence_mu

                if t_total_used_mu >= time_step_mu * (1 + i_step):
                    logger.error(
                        "Ramper writes up to step %s / %s took %.3f us which is "
                        "longer than the ramp to this step (%.3f us) - "
                        "please increase the time between steps",
                        i_step,
                        num_points_for_loop,
                        self.core.mu_to_seconds(t_total_used_mu) / us,
                        self.core.mu_to_seconds(time_step_mu * (1 + i_step)) / us,
                    )
                    raise RuntimeError("Ramper writes took longer than one timestep")

                t_start_this_step_mu += time_step_mu
                at_mu(t_start_this_step_mu)

        # Finally, ensure that the stage took the right duration overall
        at_mu(t_start_sequence_mu)
        delay(self.duration.get())

        if self.debug_enabled:
            logger.info('Saving dma trace as "%s"', self.fqn)

    @portable
    def _calc_step_size(
        self, start: TFloat, end: TFloat, num_points: TInt32
    ) -> TFloat:  # noqa
        if num_points > 1:
            return (end - start) / float(num_points - 1)
        else:
            return end - start

    @kernel
    def precalculate_dma_handle(self):
        """
        Call this method to precalculate the handle of this phase's DMA
        sequences, making its execution a lot faster.

        You must ensure that no other DMA sequences are recorded after this
        method is called otherwise the handle will become invalid. That's why
        this step is not done automatically as part of device_setup.
        """
        self.dma_handle = self.core_dma.get_handle(self.fqn)
        self.dma_handle_valid = True

    @kernel
    def do(self):
        """
        Perform the ramps (or steps) associated with this class, as configured
        by the parameters

        Advances the timeline to the end of the ramp
        """

        t_end_mu = now_mu() + self.core.seconds_to_mu(self.duration.get())

        # It's nicer to use handles here instead of string lookup.
        # Unfortunately, the DMA handle changes whenever another DMA sequence is
        # recorded, so this Fragment can't handle the case that another Fragment
        # uses DMA after this Fragment's device_setup completes. If the user
        # needs the performance of pre-pre-computed handles, they should call
        # precalculate_dma_handle before this method.
        if self.dma_handle_valid:
            self.core_dma.playback_handle(self.dma_handle)
        else:
            logger.warning(
                "You should .precalculate_dma_handle the DMA handle for %s at the start"
                " of run_once to avoid the overhead of string lookups",
                self.fqn,
            )
            self.core_dma.playback(self.fqn)

        # Ensure that the timeline points to the end of the phase, not just the
        # final RTIO point
        at_mu(t_end_mu)
