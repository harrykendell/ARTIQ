import logging
from typing import List, Dict, Tuple

from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import at_mu
from artiq.experiment import delay
from artiq.experiment import delay_mu
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import portable
from artiq.experiment import TFloat
from artiq.experiment import TInt32
from artiq.experiment import TList
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle
from numpy import int32
from numpy import int64

from repository.utils.dummy_devices import DummyAD9910
from repository.utils.dummy_devices import DummySUServoChannel
from repository.fragments.suservo_frag import SUServoFrag

logger = logging.getLogger(__name__)


class GeneralRampingPhase(Fragment):
    """
    Template fragment for a phase of the experiment which allows:

        * Ramping of SUServo setpoints
        * Ramping of AD9910 detunings and amplitudes
        * General ramping of generic float parameters (e.g. for currents in a
          coil)

    This fragment should be subclassed for each desired phase. Default settings
    for its parameters can be set by setting the appropriate class variable.

    Ramps can be daisy-chained together. To do this, see
    :meth:`~.daisy_chain_with_previous_phase`.

    ## Intensity and detuning ramps

    To ramp the intensity of beams controlled by SUServos or detunings
    controlled by Urukuls, you could use a phase like e.g.::

        class ExampleRampingPhase(GeneralRampingPhase):
            duration_default = 50e-3

            suservos = [
                "suservo_example_a",
                "suservo_example_b",
                "suservo_example_c",
            ]
            default_suservo_nominal_setpoints = [1.0, 2.0, 0.01]
            default_suservo_setpoint_multiples_start = [1.0, 2.5, 100]
            default_suservo_setpoint_multiples_end = [0.0, 2.5, 1]

            urukuls = [
                "ad9910_example_a", "ad9910_example_b",
            ]
            default_urukul_nominal_frequencies = [340e6, 200e6]
            default_urukul_detunings_start = [1e6, 0.0]
            default_urukul_detunings_end = [-1e6, 0.0]
            default_urukul_amplitudes_start = [1.0] * 2
            default_urukul_amplitudes_end = [1.0] * 2

    ### General ramping

    To ramp general parameters that aren't SUServos or AD9910s, you can define
    `general_setter_starts` and `general_setter_ends`. You must redefine the
    :meth:`~.general_setter` method, to do something with a vector of floats the
    same size as your `general_setter_starts` and `general_setter_ends` arrays.
    E.g.::

        class DemoPhase(GeneralRampingPhase):
            general_setter_names = ["some_current_1", "some_current_2"]
            general_setter_param_options = [
                {"min": 0, "max": 150, "unit": "A"},
                {"min": 0, "max": 10,  "unit": "A"},
            ]
            general_setter_default_starts = [100.0, 10.0]
            general_setter_default_ends = [10.0, 5.0]

            @kernel
            def general_setter(self, vals: TList(TFloat)):
                # Ideally do something more interesting than this:
                print(vals)

    This method will be called once for each step of the ramp and passed a list
    of floats of the same size as `self.general_setter_starts`. You can use this
    to implement arbitary ramps, e.g. of currents in a coil.

    ### Good-to-knows

    Lookup of pre-recorded sequences is slow, but can be done before the
    sequence runs. To do this, use :meth:`~.precalculate_dma_handle` before
    calling :meth:`~.do_phase`.

    By default, we actually end the ramp 1 timestep before the end of "duration"
    so that phases can be daisy-chained together simply by calling `do_phase`
    over and over again. I.e. for a 5ms ramp with 1ms points, we will have steps
    at::

        0ms (initial values), 1ms, 2ms, 3ms, 4ms

    ...and nothing at 5ms. The ramps therefore never quite reach their final
    values, on the assumption that the next phase will write these.

    If you would like the final values to be set as well, set `add_final_point =
    True`.
    """

    time_step_default = 100e-6

    duration_default: float = None

    urukuls: List[str] = []
    default_urukul_nominal_frequencies: List[float] = []
    default_urukul_detunings_start: List[float] = []
    default_urukul_detunings_end: List[float] = []
    default_urukul_amplitudes_start: List[float] = []
    default_urukul_amplitudes_end: List[float] = []

    suservos: List[str] = []
    default_suservo_nominal_setpoints: List[float] = []
    default_suservo_setpoint_multiples_start: List[float] = []
    default_suservo_setpoint_multiples_end: List[float] = []

    general_setter_names: List[str] = []
    general_setter_param_options: List[Dict] = []
    general_setter_default_starts: List[float] = []
    general_setter_default_ends: List[float] = []

    add_final_point = False
    """
    If set to True, this phase will end by writing the final point at
    t=duration. Otherwise it will omit this point, assuming that the next phase
    will write it
    """

    def validate_attributes(self):
        assert self.duration_default is not None

        # validate the class attributes to make sure this class was declared correctly
        assert len(self.urukuls) == len(set(self.urukuls)), TypeError(
            "self.urukuls contains duplicate entries"
        )
        assert len(self.default_urukul_nominal_frequencies) == len(
            self.urukuls
        ), TypeError(
            "default_urukul_nominal_frequencies must have same length as self.urukuls"
        )
        assert len(self.default_urukul_detunings_start) == len(self.urukuls), TypeError(
            "default_urukul_detunings_start must have same length as self.urukuls"
        )
        assert len(self.default_urukul_detunings_end) == len(self.urukuls), TypeError(
            "default_urukul_detunings_end must have same length as self.urukuls"
        )

        assert len(self.default_urukul_amplitudes_start) == len(
            self.urukuls
        ), TypeError(
            "default_urukul_amplitudes_start must have same length as self.urukuls"
        )
        assert len(self.default_urukul_amplitudes_end) == len(self.urukuls), TypeError(
            "default_urukul_amplitudes_end must have same length as self.urukuls"
        )

        assert len(self.suservos) == len(set(self.suservos)), TypeError(
            "self.suservos_for_intensity contains duplicate entries"
        )
        assert len(self.default_suservo_setpoint_multiples_start) == len(
            self.suservos
        ), TypeError(
            "self.default_syservo_setpoints_start must have same length as self.suservos_for_intensity"
        )
        assert len(self.default_suservo_setpoint_multiples_end) == len(
            self.suservos
        ), TypeError(
            "self.default_syservo_setpoints_end must have same length as self.suservos_for_intensity"
        )

        assert len(self.general_setter_default_starts) == len(
            self.general_setter_default_ends
        ), TypeError(
            "self.general_setters_start must have same length as self.general_setters_end"
        )
        assert len(self.general_setter_names) == len(
            self.general_setter_default_ends
        ), TypeError(
            "self.general_setter_names must have same length as self.general_setters_end"
        )

        if len(self.general_setter_param_options) == 0:
            self.general_setter_param_options = [
                {} for _ in range(len(self.general_setter_default_starts))
            ]

        assert len(self.general_setter_param_options) == len(
            self.general_setter_default_ends
        ), TypeError(
            "self.general_setter_param_options must have same length as self.general_setters_end"
        )

    def build_fragment(self):
        self.validate_attributes()

        # %% Devices

        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        # ARTIQ doesn't like empty lists because it doesn't know what type they
        # are. Rather than work around this, I make sure that all list are at
        # least 1 long by adding a dummy object if they're empty. Here are those
        # dummy objects:
        self.dummy_ad9910 = DummyAD9910()
        self.dummy_suservo = DummySUServoChannel()

        # I also need to loop over parameter handles, so I must make a dummy
        # parameter to pass. I'll override it so that it doesn't appear in the
        # parameter listing
        self.dummy_param = self.setattr_param(
            "dummy_param", FloatParam, "Dummy parameter - ignore me", default=0.0
        )
        self.override_param("dummy_param", 0.0)

        # Build ndscan parameters for all the ramping variables and arrays of
        # setters for the kernel to use
        self.suservo_setters_and_param_handles = self._build_suservos()
        self.ad9910_channels_and_param_handles = self._build_ad9910s()
        self.general_setter_param_handles = self._build_general_setter_param_handles()

        # %% Other parameters

        self.setattr_param(
            "duration",
            FloatParam,
            "Duration of phase",
            default=self.duration_default,
            min=0.0,
            unit="ms",
        )
        self.setattr_param(
            "time_step",
            FloatParam,
            "Gap between steps",
            default=self.time_step_default,
            min=0.0,
            unit="us",
        )

        self.duration: FloatParamHandle
        self.time_step: FloatParamHandle

        # %% Kernel variables
        self.debug_enabled = logger.isEnabledFor(logging.DEBUG)
        self.dma_handle = (int32(0), int64(0), int32(0), False)
        self.dma_handle_valid = False

        # %% Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "debug_enabled",
        }

    @kernel
    def general_setter(self, vals: TList(TFloat)):
        pass

    def _build_general_setter_param_handles(self):
        general_setter_in_use = len(self.general_setter_default_starts) > 0

        general_setter_param_handles: List[
            Tuple[
                FloatParamHandle,
                FloatParamHandle,
            ]
        ] = []

        if general_setter_in_use:
            for name, options, start, end in zip(
                self.general_setter_names,
                self.general_setter_param_options,
                self.general_setter_default_starts,
                self.general_setter_default_ends,
            ):
                # For each passed parameter to the general setter, make an NDScan parameter
                start_handle = self.setattr_param(
                    f"{name}_start",
                    FloatParam,
                    f"Start value for {name}",
                    default=start,
                    **options,
                )

                end_handle = self.setattr_param(
                    f"{name}_end",
                    FloatParam,
                    f"End value for {name}",
                    default=end,
                    **options,
                )

                general_setter_param_handles.append((start_handle, end_handle))

        else:
            # If there's no general setter then don't make any parameters. We
            # must still return a list of ParamHandles though otherwise the
            # compiler will break, so pass out the dummy handle.
            general_setter_param_handles.append((self.dummy_param, self.dummy_param))

        return general_setter_param_handles

    def _build_suservos(self):
        suservo_setters_and_param_handles: List[
            Tuple[
                SUServoFrag,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
            ]
        ] = []

        for suservo_name, setpoint_nominal, setpoint_start, setpoint_end in zip(
            self.suservos,
            self.default_suservo_nominal_setpoints,
            self.default_suservo_setpoint_multiples_start,
            self.default_suservo_setpoint_multiples_end,
        ):
            # For each requested SUServo, get a setter Fragment for it and
            # define parameters for the nominal setpoint, and the multiples of
            # that nominal value that this ramping phase should start and end
            # with. These will take default values defined by the class
            # attributes when a concrete instance of this class is created, but
            # the user will be able to override those value through normal
            # NDScan behaviour.
            setter = self.setattr_fragment(
                f"setter_{suservo_name}", SUServoFrag, suservo_name
            )

            setpoint_nominal_handle = self.setattr_param(
                f"setpoint_nominal_{suservo_name}",
                FloatParam,
                f"Nominal setpoint for {suservo_name}",
                min=0,
                unit="V",
                default=setpoint_nominal,
            )

            setpoint_start_handle = self.setattr_param(
                f"setpoint_multiple_start_{suservo_name}",
                FloatParam,
                f"Multiple of nominal setpoint at start of ramp for {suservo_name}",
                min=0,
                default=setpoint_start,
            )

            setpoint_end_handle = self.setattr_param(
                f"setpoint_multiple_end_{suservo_name}",
                FloatParam,
                f"Multiple of nominal setpoint at end of ramp for {suservo_name}",
                min=0,
                default=setpoint_end,
            )

            suservo_setters_and_param_handles.append(
                (
                    setter,
                    setpoint_nominal_handle,
                    setpoint_start_handle,
                    setpoint_end_handle,
                )
            )

        # Add a global parameter that allows ramping all the suservo setpoints at the same time
        self.setattr_param(
            "setpoint_global_multiple_start",
            FloatParam,
            "Global multiple of nominal setpoint at start of ramp for all SUServos",
            min=0,
            default=1.0,
        )
        self.setattr_param(
            "setpoint_global_multiple_end",
            FloatParam,
            "Global multiple of nominal setpoint at end of ramp for all SUServos",
            min=0,
            default=1.0,
        )
        self.setpoint_global_multiple_start: FloatParamHandle
        self.setpoint_global_multiple_end: FloatParamHandle

        if not suservo_setters_and_param_handles:
            # If we don't have any SUServos to ramp, add a dummy object so that
            # the compiler doesn't complain, with pointers to a dummy parameter
            # handle
            suservo_setters_and_param_handles.append(
                (
                    self.dummy_suservo,
                    self.dummy_param,
                    self.dummy_param,
                    self.dummy_param,
                )
            )

        return suservo_setters_and_param_handles

    def _build_ad9910s(self):
        ad9910_channels_and_param_handles: List[
            Tuple[
                AD9910,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
                FloatParamHandle,
            ]
        ] = []

        for (
            urukul_channel_name,
            frequency_nominal,
            detuning_start,
            detuning_end,
            amplitude_start,
            amplitude_end,
        ) in zip(
            self.urukuls,
            self.default_urukul_nominal_frequencies,
            self.default_urukul_detunings_start,
            self.default_urukul_detunings_end,
            self.default_urukul_amplitudes_start,
            self.default_urukul_amplitudes_start,
        ):
            # For each requested SUServo, get a setter Fragment for it and
            # define parameters for the nominal setpoint, and the multiples of
            # that nominal value that this ramping phase should start and end
            # with. These will take default values defined by the class
            # attributes when a concrete instance of this class is created, but
            # the user will be able to override those value through normal
            # NDScan behaviour.
            channel: AD9910 = self.get_device(urukul_channel_name)

            nominal_freq_handle = self.setattr_param(
                f"frequency_nominal_{urukul_channel_name}",
                FloatParam,
                f"Nominal frequency for {urukul_channel_name}",
                min=0,
                unit="MHz",
                default=frequency_nominal,
            )

            detuning_start_handle = self.setattr_param(
                f"detuning_start_{urukul_channel_name}",
                FloatParam,
                f"Detuning from nominal frequency at start of ramp for {urukul_channel_name}",
                unit="MHz",
                default=detuning_start,
            )

            detuning_end_handle = self.setattr_param(
                f"detuning_end_{urukul_channel_name}",
                FloatParam,
                f"Detuning from nominal frequency at end of ramp for {urukul_channel_name}",
                unit="MHz",
                default=detuning_end,
            )

            amplitude_start_handle = self.setattr_param(
                f"amplitude_start_{urukul_channel_name}",
                FloatParam,
                f"Amplitude at start of ramp for {urukul_channel_name}",
                min=0,
                default=amplitude_start,
            )

            amplitude_end_handle = self.setattr_param(
                f"amplitude_end_{urukul_channel_name}",
                FloatParam,
                f"Amplitude at end of ramp for {urukul_channel_name}",
                min=0,
                default=amplitude_end,
            )

            ad9910_channels_and_param_handles.append(
                (
                    channel,
                    nominal_freq_handle,
                    detuning_start_handle,
                    detuning_end_handle,
                    amplitude_start_handle,
                    amplitude_end_handle,
                )
            )

        if not ad9910_channels_and_param_handles:
            # If we don't have any AD9910s to ramp, add a dummy object so that
            # the compiler doesn't complain, with pointers to a dummy parameter
            # handle
            ad9910_channels_and_param_handles.append(
                (
                    self.dummy_ad9910,
                    self.dummy_param,
                    self.dummy_param,
                    self.dummy_param,
                    self.dummy_param,
                    self.dummy_param,
                )
            )

        return ad9910_channels_and_param_handles

    def daisy_chain_with_previous_phase(
        self,
        previous_phase: "GeneralRampingPhase",
        suservos=[],
        ad9910s=[],
        general_setters=[],
        bind_nominal_setpoints=True,
    ):
        """
        Bind the start points of the specified ramping parameters to the end
        points of the previous ramping phase's parameters. Also, bind *all*
        suservo nominal setpoints if they are present in the previous phase.

        This is useful for chaining ramping phases together to avoid
        discontinuous jumps in a parameter and/or to share the same nominal
        setpoints for the SUServos.

        If `suservos` is set to the string "all" instead of a list of which
        SUServos to daisy-chain, daisy-chain all of them and also daisy-chain
        the `setpoint_global_multiple_...` params.

        If `suservos` is an empty list (the default), this will only bind the
        nominal setpoints, retaining the ability for discontinuous jumps between
        phases.

        Parameters
        ----------
        previous_phase : GeneralRampingPhase
            The previous ramping phase to bind the start points to. Must ramp
            the same things as this phase.
        suservos : list(str)
            List of suservos to daisy-chain, or the string "all"
        ad9910s : list(str)
            List of ad9910s to daisy-chain
        general_setters : list(str)
            List of general_setter_names to daisy-chain
        bind_nominal_setpoints : bool, default=True
            Bind *all* nominal setpoints that are present in the previous phase
        """

        if ad9910s:
            raise NotImplementedError("Binding AD9910s is not yet implemented")

        if general_setters:
            raise NotImplementedError("Binding general setters is not yet implemented")

        if isinstance(suservos, str) and suservos == "all":
            # Special case: override all the SUServos
            suservos = self.suservos

            # Also, daisy-chain the "setpoint_global_multiple" params
            self.bind_param(
                "setpoint_global_multiple_start",
                previous_phase.setpoint_global_multiple_end,
            )

        # For each suservo device in this phase, look for it in the previous
        # phase. If found, bind this phase's nominal setpoint to that of the
        # previous phase
        for suservo_name, setters_and_handlers in zip(
            self.suservos, self.suservo_setters_and_param_handles
        ):
            if suservo_name in previous_phase.suservos:
                (
                    _,
                    setpoint_nominal_handle,
                    setpoint_start_handle,
                    setpoint_end_handle,
                ) = setters_and_handlers

                # Bind this suservo's nominal setpoint to the previous phase's
                if bind_nominal_setpoints:
                    self.bind_param(
                        setpoint_nominal_handle.name,
                        getattr(previous_phase, setpoint_nominal_handle.name),
                    )

                # If this suservo is one of the ones to daisy-chain, do so
                if suservo_name in suservos:
                    self.bind_param(
                        setpoint_start_handle.name,
                        getattr(previous_phase, setpoint_end_handle.name),
                    )

    @portable
    def _calc_step_size(self, start: TFloat, end: TFloat, num_points: TInt32) -> TFloat:
        if num_points > 1:
            return (end - start) / float(num_points - 1)
        else:
            return end - start

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

        # Recalculate using the rounded num_points to ensure that the phase has the
        # right duration
        time_step_mu = self.core.seconds_to_mu(
            self.duration.get() / float(num_points - 1)
        )

        # Compute step sizes and initial values for the general ramp
        general_values = [0.0] * len(self.general_setter_param_handles)
        general_steps = [0.0] * len(self.general_setter_param_handles)

        for i in range(len(self.general_setter_param_handles)):
            start_handle = self.general_setter_param_handles[i][0]
            end_handle = self.general_setter_param_handles[i][1]

            general_values[i] = start_handle.get()
            general_steps[i] = self._calc_step_size(
                start_handle.get(), end_handle.get(), num_points
            )

        suservo_values = [0.0] * len(self.suservo_setters_and_param_handles)
        suservo_steps = [0.0] * len(self.suservo_setters_and_param_handles)

        suservo_global_multiple_start = self.setpoint_global_multiple_start.get()
        suservo_global_multiple_end = self.setpoint_global_multiple_end.get()

        for i in range(len(self.suservo_setters_and_param_handles)):
            nom_setpoint_handle = self.suservo_setters_and_param_handles[i][1]
            start_multiple_handle = self.suservo_setters_and_param_handles[i][2]
            end_multiple_handle = self.suservo_setters_and_param_handles[i][3]

            # Get the start point for all the SUServo intensities
            nominal_value = nom_setpoint_handle.get()
            suservo_values[i] = (
                nominal_value
                * suservo_global_multiple_start
                * start_multiple_handle.get()
            )

            # Calculate the step sizes for all the SUServo steps
            suservo_steps[i] = self._calc_step_size(
                nominal_value
                * suservo_global_multiple_start
                * start_multiple_handle.get(),
                nominal_value * suservo_global_multiple_end * end_multiple_handle.get(),
                num_points,
            )

        frequency_values = [0.0] * len(self.ad9910_channels_and_param_handles)
        frequency_steps = [0.0] * len(self.ad9910_channels_and_param_handles)
        amplitude_steps = [0.0] * len(self.ad9910_channels_and_param_handles)
        amplitude_values = [0.0] * len(self.ad9910_channels_and_param_handles)

        for i in range(len(self.ad9910_channels_and_param_handles)):
            nominal_freq_handle = self.ad9910_channels_and_param_handles[i][1]
            detuning_start_handle = self.ad9910_channels_and_param_handles[i][2]
            detuning_end_handle = self.ad9910_channels_and_param_handles[i][3]
            amplitude_start_handle = self.ad9910_channels_and_param_handles[i][4]
            amplitude_end_handle = self.ad9910_channels_and_param_handles[i][5]

            # Get the start point for all the AD9910 parameters
            frequency_values[i] = (
                nominal_freq_handle.get() + detuning_start_handle.get()
            )
            amplitude_values[i] = amplitude_start_handle.get()

            # Calculate the step sizes for all the AD9910 channels
            frequency_steps[i] = self._calc_step_size(
                detuning_start_handle.get(), detuning_end_handle.get(), num_points
            )
            amplitude_steps[i] = self._calc_step_size(
                amplitude_start_handle.get(), amplitude_end_handle.get(), num_points
            )

        if self.debug_enabled:
            logger.info("frequency_steps: %s", frequency_steps)
            logger.info("amplitude_steps: %s", amplitude_steps)
            logger.info("general_steps: %s", general_steps)
            logger.info("frequency_values: %s", frequency_values)
            logger.info("amplitude_values: %s", amplitude_values)
            logger.info("general_values: %s", general_values)

        # Record these ramping parameters into a DMA sequence
        with self.core_dma.record(self.fqn):
            t_start_sequence_mu = now_mu()
            t_start_this_step_mu = now_mu()
            t_one_rtio_cycle_mu = int64(self.core.ref_multiplier)

            # Play the ramp
            if self.add_final_point:
                num_points_for_loop = num_points
            else:
                num_points_for_loop = num_points - 1

            for i_step in range(num_points_for_loop):
                if self.debug_enabled:
                    logger.info("Saving trace %d of %d", i_step, num_points)

                # %% Write the general setter steps

                # Do this first since it often writes into the past (e.g. for
                # Zotinos) and we wish to avoid using multiple lanes if possible
                #
                # Unlike with the SUServos and AD9910s, we pass all the new
                # values at once to the setter. It can decide what to do with
                # them
                self.general_setter(general_values)

                # Increment all the values by their steps
                for i in range(len(general_values)):
                    general_values[i] += general_steps[i]

                delay_mu(t_one_rtio_cycle_mu)  # Avoid using multiple lanes

                # %% Set AD9910 frequencies
                for i in range(len(self.ad9910_channels_and_param_handles)):
                    ad9910 = self.ad9910_channels_and_param_handles[i][0]

                    if self.debug_enabled:
                        logger.info(
                            "Setting AD9910 %s to %.6f, amplitude=%f",
                            ad9910,
                            frequency_values[i],
                            amplitude_values[i],
                        )

                    ad9910.set(
                        frequency=frequency_values[i], amplitude=amplitude_values[i]
                    )
                    delay_mu(t_one_rtio_cycle_mu)  # Avoid using multiple lanes

                    frequency_values[i] += frequency_steps[i]
                    amplitude_values[i] += amplitude_steps[i]

                # %% Set suservo setpoints
                for i in range(len(self.suservo_setters_and_param_handles)):
                    suservo_channel = self.suservo_setters_and_param_handles[i][0]
                    suservo_channel.set_setpoint(suservo_values[i])
                    suservo_values[i] += suservo_steps[i]

                    delay_mu(t_one_rtio_cycle_mu)

                t_total_used_mu = now_mu() - t_start_this_step_mu

                if t_total_used_mu >= time_step_mu:
                    logger.error(
                        "Ramper writes took %.3f us which is longer than one timestep (%.3f us) - please increase the time between steps",
                        1e6 * self.core.mu_to_seconds(t_total_used_mu),
                        1e6 * self.core.mu_to_seconds(time_step_mu),
                    )
                    raise RuntimeError("Ramper writes took longer than one timestep")

                t_start_this_step_mu += time_step_mu
                at_mu(t_start_this_step_mu)

        # Finally, ensure that the stage took the right duration overall
        at_mu(t_start_sequence_mu)
        delay(self.duration.get())

        if self.debug_enabled:
            logger.info('Saving dma trace as "%s"', self.fqn)

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
    def do_phase(self):
        """
        Perform the ramps (or steps) associated with this phase, as configured
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
            self.core_dma.playback(self.fqn)

        # Ensure that the timeline points to the end of the phase, not just the
        # final RTIO point
        at_mu(t_end_mu)

    def bind_ad9910_frequency_params(self, param_handles: List[FloatParamHandle]):
        """
        Convience method to call `.bind_param` for all the AD9910 nominal frequency parameters
        """
        for this_channel, target_handle in zip(
            self.ad9910_channels_and_param_handles, param_handles
        ):
            nominal_frequency_param_handle = this_channel[1]
            self.bind_param(
                param_name=nominal_frequency_param_handle.name, source=target_handle
            )

    def bind_suservo_setpoint_params(self, param_handles: List[FloatParamHandle]):
        """
        Convience method to call `.bind_param` for all the SUServo nominal setpoint parameters
        """
        for this_channel, target_handle in zip(
            self.suservo_setters_and_param_handles, param_handles
        ):
            setpoint_nominal_handle = this_channel[1]
            self.bind_param(
                param_name=setpoint_nominal_handle.name, source=target_handle
            )
