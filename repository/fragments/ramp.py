import logging
from typing import List, Tuple

from numpy import int32, int64

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.experiment import TFloat, TInt32, kernel, portable
from artiq.language.core import at_mu, delay, delay_mu, now_mu
from artiq.language.units import MHz, ms, us
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import FloatParam, FloatParamHandle, ParamHandle
from repository.fragments.eom_setter import EomFrag
from repository.fragments.supply_setter import SetSupplies
from repository.models import DEVICE, Eom, SUServoedBeam, VDrivenSupply
from repository.utils.dummy_devices import (
    DummyEom,
    DummyEomFrag,
    DummySetSupplies,
    DummySUServoChannel,
    DummySUServoedBeam,
    DummyVDrivenSupply,
)

logger = logging.getLogger(__name__)


class DefaultFlag:
    def __repr__(self):
        return "<DEFAULT THIS DEVICE>"

    def __str__(self):
        return "<default this device>"

    def __bool__(self):
        return False


default = DefaultFlag()


class Ramp(Fragment):
    """
    ------
    THIS CLASS MUST BE SUBCLASSED TO BE USEFUL
    ------

    Fragment representing a ramp in an experiment:

    - SUServo Frequency/Setpoint
    - VDrivenSupply Output
    - Eom Amplitude/Frequency (although frequency takes ~0.4ms per step)

    Values can be set to:
        - `default`: explicitly use the default value for that device
        - `ParamHandle`: use the provided parameter handle
        - `Ramp`: use the values from the end of this ramp
        - `float`: use the provided value

    Example usage
    -------------
    Here we don't ramp any suservos::

        class CMOT_Ramp(Ramp):

            duration_default = 50*ms
            supplies = VDrivenSupply["X1", "X2", "push_780"]
            supplies_start = [
                default,
                OTHER_RAMP,
                -DETUNING["CMOT"],
            supplies_end = [
                VDrivenSupply["X1"].default_output * 1.5,
                VDrivenSupply["X2"].default_output * 1.5,
                DETUNING["CMOT"],
            ]

            eoms = [Eom["repump"]]
            eom_att_end = [
                Eom["repump"].attenuation + 10*dB,
            ]
    """

    time_step_default = 50 * us
    duration_default: float = None
    add_final_point = True

    suservos: List[SUServoedBeam] = None
    suservos_used = True
    suservo_setpoint_start: List[float] = default
    suservo_setpoint_end: List[float] = default
    suservo_detuning_start: List[float] = default
    suservo_detuning_end: List[float] = default

    eoms: List[Eom] = None
    eoms_used = True
    eom_detuning_start: List[float] = default
    eom_detuning_end: List[float] = default
    do_eom_detuning = False  # avoid if we can as this is slow
    eom_att_start: List[float] = default
    eom_att_end: List[float] = default

    supplies: List[VDrivenSupply] = None
    supplies_used = True
    supplies_start: List[float] = default
    supplies_end: List[float] = default

    def validate(self):
        assert self.duration_default is not None

        # Validate suservos
        if self.suservos is None:
            self.suservos_used = False
            self.suservos: List[SUServoedBeam] = [DummySUServoedBeam]
        assert len(self.suservos) == len(set([ss.name for ss in self.suservos]))

        # Validate eoms
        if self.eoms is None:
            self.eoms_used = False
            self.eoms: List[Eom] = [DummyEom]
        assert len(self.eoms) == len(set([eom.name for eom in self.eoms]))

        # Validate supplies
        if self.supplies is None:
            self.supplies_used = False
            self.supplies: List[VDrivenSupply] = [DummyVDrivenSupply]
        assert len(self.supplies) == len(set([supply.name for supply in self.supplies]))

    def make_or_reuse_param(
        self,
        values_name: str,
        devices: list[DEVICE],
        num: int,
        default_value,
        unit: str,
    ):
        """
        Returns the parameter handle for the given device value:
        - If the value is a ParamHandle, it is returned
        - If the value is a Ramp, the end value ParamHandle is returned
        - Otherwise, a new ParamHandle is created (but suppressed if its a default)

        Parameters
        ----------
        values_name : str
            The name of the variable `values` in the parent class
            e.g. "supplies_start" or "eom_detuning_end"
        devices : list[DEVICE]
            The list of devices
            e.g. self.supplies or self.suservos
        num : int
            The index of the current device
        default_value : float
            The default value to use if the value is not set
            e.g. self.supplies[num].default_output
        unit : str
            The unit of the parameter
            e.g. "V" or "MHz"
        """
        param_name = f"{values_name}_{devices[num].name}"
        values = getattr(self, values_name)
        desc = (
            f"{self.__class__.__name__}: {values_name.replace('_', ' ').capitalize()} -"
            f" {devices[num].name}"
        )

        if (values is not default) and isinstance(values[num], ParamHandle):
            # We've been given a param already
            return values[num]

        if (values is not default) and isinstance(values[num], Ramp):
            # We've been given a ramp so just use the end value for this device
            if values_name.endswith("_start"):
                key = values_name[:-6] + f"_end_{devices[num].name}"
            elif values_name.endswith("_end"):
                key = values_name[:-4] + f"_start_{devices[num].name}"
            if not hasattr(values[num], key):
                raise RuntimeError(
                    f"Cannot follow ramp {values[num].__class__.__name__} for {desc} - "
                    "transitive bindings are not allowed"
                )
            return values[num].__dict__[key]

        # We need to create a new param
        if values and (values[num] is not default):
            # We have a value to use
            default_value = values[num]

        param_handle = self.setattr_param(
            name=param_name,
            param_class=FloatParam,
            description=desc,
            default=default_value,
            unit=unit,
        )
        if not values or values[num] is default:
            if values_name.endswith("_end"):
                start_vals = getattr(self, f"{values_name[:-4]}_start")
                if not (not start_vals or start_vals[num] is default):
                    logging.warning(
                        f"Did you mean to use a default for {desc} but not it's start?"
                    )
            # We don't want to expose defaulted values as they follow devices.py
            # and it would give two sources of truth
            self.override_param(f"{param_name}", default_value)
        return param_handle

    def _build_suservos(self):
        """
        Creates SUServoChannels to control the SUServos in this ramp,
        paired with param handles for
        - suservo_detuning_start_{name}
        - suservo_detuning_end_{name}
        - suservo_setpoint_start_{name}
        - suservo_setpoint_end_{name}

        [0: setter, 1: suservo_detuning_start, 2: suservo_detuning_end, 3: suservo_setpoint_start, 4: suservo_setpoint_end]
        """
        setters_and_param_handles: List[
            Tuple[
                SUServoChannel,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
            ]
        ] = []
        if self.suservos:
            for i in range(len(self.suservos)):
                setters_and_param_handles.append((
                    self.get_device(self.suservos[i].suservo_device),
                    self.make_or_reuse_param(
                        values_name="suservo_detuning_start",
                        devices=self.suservos,
                        num=i,
                        default_value=0.0 * MHz,
                        unit="MHz",
                    ),
                    self.make_or_reuse_param(
                        values_name="suservo_detuning_end",
                        devices=self.suservos,
                        num=i,
                        default_value=0.0 * MHz,
                        unit="MHz",
                    ),
                    self.make_or_reuse_param(
                        values_name="suservo_setpoint_start",
                        devices=self.suservos,
                        num=i,
                        default_value=self.suservos[i].setpoint,
                        unit="V",
                    ),
                    self.make_or_reuse_param(
                        values_name="suservo_setpoint_end",
                        devices=self.suservos,
                        num=i,
                        default_value=self.suservos[i].setpoint,
                        unit="V",
                    ),
                ))
        else:
            # If we don't have any SUServos to ramp, add a dummy object so that
            # the compiler doesn't complain, with points to a dummy parameter
            # handle
            setters_and_param_handles.append((
                DummySUServoChannel(),
                self.dummy_param,
                self.dummy_param,
                self.dummy_param,
                self.dummy_param,
            ))

        return setters_and_param_handles

    def _build_eoms(self):
        """
        Creates EomFrag to control the Eoms in this ramp,
        paired with param handles for
        - eom_detuning_start_{name}
        - eom_detuning_end_{name}
        - eom_att_start_{name}
        - eom_att_end_{name}

        [0: setter, 1: eom_detuning_start, 2: eom_detuning_end, 3: eom_att_start, 4: eom_att_end]
        """
        setters_and_param_handles: List[
            Tuple[
                EomFrag,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
            ]
        ] = []
        if self.eoms:
            for i in range(len(self.eoms)):
                setters_and_param_handles.append((
                    self.setattr_fragment(
                        self.eoms[i].name,
                        EomFrag,
                        self.eoms[i],
                        init=False,
                    ),
                    self.make_or_reuse_param(
                        values_name="eom_detuning_start",
                        devices=self.eoms,
                        num=i,
                        default_value=0.0 * MHz,
                        unit="MHz",
                    ),
                    self.make_or_reuse_param(
                        values_name="eom_detuning_end",
                        devices=self.eoms,
                        num=i,
                        default_value=0.0 * MHz,
                        unit="MHz",
                    ),
                    self.make_or_reuse_param(
                        values_name="eom_att_start",
                        devices=self.eoms,
                        num=i,
                        default_value=self.eoms[i].attenuation,
                        unit="dB",
                    ),
                    self.make_or_reuse_param(
                        values_name="eom_att_end",
                        devices=self.eoms,
                        num=i,
                        default_value=self.eoms[i].attenuation,
                        unit="dB",
                    ),
                ))
        else:
            # If we don't have any eoms to ramp, add a dummy object so that
            # the compiler doesn't complain, with points to a dummy parameter
            # handle
            setters_and_param_handles.append((
                DummyEomFrag(),
                self.dummy_param,
                self.dummy_param,
                self.dummy_param,
                self.dummy_param,
            ))

        return setters_and_param_handles

    def _build_supplies(self):
        """
        Creates SetSupplies to control the VDrivenSupplies in this ramp,
        paired with param handles for
        - supplies_start_{name}
        - supplies_end_{name}

        [0: setter, 1: supplies_start, 2: supplies_end]
        """
        setters_and_param_handles: List[
            Tuple[
                SetSupplies,
                FloatParamHandle,
                FloatParamHandle,
            ]
        ] = []
        if self.supplies:
            for i in range(len(self.supplies)):
                setters_and_param_handles.append((
                    self.setattr_fragment(
                        self.supplies[i].name,
                        SetSupplies,
                        self.supplies[i],
                        init=False,
                    ),
                    self.make_or_reuse_param(
                        values_name="supplies_start",
                        devices=self.supplies,
                        num=i,
                        default_value=self.supplies[i].default_output,
                        unit=self.supplies[i].unit,
                    ),
                    self.make_or_reuse_param(
                        values_name="supplies_end",
                        devices=self.supplies,
                        num=i,
                        default_value=self.supplies[i].default_output,
                        unit=self.supplies[i].unit,
                    ),
                ))
        else:
            # If we don't have any supplies to ramp, add a dummy object so that
            # the compiler doesn't complain, with points to a dummy parameter
            # handle
            setters_and_param_handles.append((
                DummySetSupplies(),
                self.dummy_param,
                self.dummy_param,
            ))

        return setters_and_param_handles

    def build_fragment(self):
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
            f"{self.__class__.__name__}: Duration of phase",
            default=self.duration_default,
            min=0.0,
            unit="ms",
        )
        self.duration: FloatParamHandle

        self.setattr_param(
            "time_step",
            FloatParam,
            f"{self.__class__.__name__}: Gap between steps",
            default=self.time_step_default,
            min=0.0,
            unit="us",
        )
        self.time_step: FloatParamHandle

        # I'll override this so that it doesn't appear in the parameter listing
        self.dummy_param = self.setattr_param(
            "dummy_param", FloatParam, "Dummy parameter - ignore me", default=0.0
        )
        self.override_param("dummy_param", 0.0)

        self.suservo_setters_params = self._build_suservos()
        self.eoms_setters_params = self._build_eoms()
        self.supplies_setters_params = self._build_supplies()

        self.validate()

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
        time_step = self.duration.get() / float(num_points)
        time_step_mu = self.core.seconds_to_mu(time_step)

        # Compute step sizes and initial values
        # [0: setter, 1: start, 2: end]
        supply_values = [0.0] * len(self.supplies)
        supply_steps = [0.0] * len(self.supplies)
        if self.supplies_used:  # only run the calculations if needed
            for i in range(len(self.supplies)):
                supply_values[i] = self.supplies_setters_params[i][1].get()
                supply_steps[i] = self._calc_step_size(
                    self.supplies_setters_params[i][1].get(),
                    self.supplies_setters_params[i][2].get(),
                    num_points,
                )

        # [0: setter, 1: detuning_start, 2: detuning_end, 3: att_start, 4: att_end]
        eom_att_values = [0.0] * len(self.eoms)
        eom_freq_values = [0.0] * len(self.eoms)
        eom_att_steps = [0.0] * len(self.eoms)
        eom_freq_steps = [0.0] * len(self.eoms)
        if self.eoms_used:  # only run the calculations if needed
            for i in range(len(self.eoms)):
                eom_att_values[i] = self.eoms_setters_params[i][3].get()
                eom_freq_values[i] = (
                    self.eoms[i].frequency + self.eoms_setters_params[i][1].get()
                )
                eom_att_steps[i] = self._calc_step_size(
                    self.eoms_setters_params[i][3].get(),
                    self.eoms_setters_params[i][4].get(),
                    num_points,
                )
                eom_freq_steps[i] = self._calc_step_size(
                    self.eoms_setters_params[i][1].get(),
                    self.eoms_setters_params[i][2].get(),
                    num_points,
                )

        # [0: setter, 1: detuning_start, 2: detuning_end, 3: setpoint_start, 4: setpoint_end]
        suservo_freq_values = [0.0] * len(self.suservos)
        suservo_setpoint_values = [0.0] * len(self.suservos)
        suservo_freq_steps = [0.0] * len(self.suservos)
        suservo_setpoint_steps = [0.0] * len(self.suservos)
        if self.suservos_used:  # only run the calculations if needed
            for i in range(len(self.suservos)):
                suservo_freq_values[i] = (
                    self.suservos[i].frequency + self.suservo_setters_params[i][1].get()
                )
                suservo_setpoint_values[i] = self.suservo_setters_params[i][3].get()
                suservo_freq_steps[i] = self._calc_step_size(
                    self.suservo_setters_params[i][1].get(),
                    self.suservo_setters_params[i][2].get(),
                    num_points,
                )
                suservo_setpoint_steps[i] = self._calc_step_size(
                    self.suservo_setters_params[i][3].get(),
                    self.suservo_setters_params[i][4].get(),
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
                logger.error(
                    "Verify this is changing the almazny not just the mirny att."
                )
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
                    for i in range(len(supply_values)):
                        self.supplies_setters_params[i][0].set_outputs(
                            [supply_values[i]]
                        )
                        supply_values[i] += supply_steps[i]

                delay_mu(14 * 7 * 4)  # Avoid using multiple lanes

                # SUServos next
                if self.suservos_used:
                    for i in range(len(self.suservos)):
                        self.suservo_setters_params[i][0].set_dds(
                            self.suservo_setters_params[i][0].servo_channel,
                            suservo_freq_values[i],
                            -1.0 * suservo_setpoint_values[i] / 10.0,
                        )
                        suservo_freq_values[i] += suservo_freq_steps[i]
                        suservo_setpoint_values[i] += suservo_setpoint_steps[i]

                        delay_mu(t_one_rtio_cycle_mu)

                # EOMs last
                if self.eoms_used:
                    for i in range(len(self.eoms)):
                        self.eoms_setters_params[i][0].set_att(eom_att_values[i])
                        eom_att_values[i] += eom_att_steps[i]
                        delay_mu(t_one_rtio_cycle_mu)
                        # freq for mirny is very slow so only set 1/10 of the time
                        if self.do_eom_detuning:
                            self.eoms_setters_params[i][0].set_freq(eom_freq_values[i])
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

        **Timeline:** advances to the end of the ramp
        """

        t_end_mu = now_mu() + self.core.seconds_to_mu(
            self.duration.get()
        )

        # It's nicer to use handles here instead of string lookup.
        # Unfortunately, the DMA handle changes whenever another DMA sequence is
        # recorded, so this Fragment can't handle the case that another Fragment
        # uses DMA after this Fragment's device_setup completes. If the user
        # needs the performance of pre-pre-computed handles, they should call
        # precalculate_dma_handle before this method.
        if self.dma_handle_valid:
            self.core_dma.playback_handle(self.dma_handle)
        else:
            if self.debug_enabled:
                logger.warning(
                    "You should .precalculate_dma_handle the DMA handle for %s at the"
                    " start of run_once to avoid the overhead of string lookups",
                    self.fqn,
                )
            self.core_dma.playback(self.fqn)

        # Ensure that the timeline points to the end of the phase, not just the
        # final RTIO point
        at_mu(t_end_mu)
