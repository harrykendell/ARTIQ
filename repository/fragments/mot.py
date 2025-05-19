import logging

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.language import delay, kernel, parallel, sequential
from artiq.language.units import A, MHz, V, dB, ms, s
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import FloatParam, FloatParamHandle
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.default_beam_setter import (
    SetBeamsToDefaults,
    make_set_beams_to_default,
)
from repository.fragments.eom_setter import EomFrag
from repository.fragments.ramp import Ramp, default
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import Eom, SUServoedBeam, VDrivenSupply

logger = logging.getLogger(__name__)

# Default constants - these can be overridden in the experiment
Γ_Rb = 6.065 * MHz  # Natural linewidth of Rb-87
DURATION = {"LOADING": 20 * s, "CMOT": 1 * ms, "PGC": 1 * ms, "ODT": 1 * ms}
SETTLE_TIME = {"CMOT": 3 * ms, "PGC": 3 * ms, "ODT": 3 * ms}
DETUNING = {"CMOT": 2.5 * Γ_Rb, "PGC": 6 * Γ_Rb}  # This is beyond the normal 2Γ
BIASES = {"X1": 0.0 * A, "X2": 0.0 * A, "Y": 0.0 * A, "Z": 0.0 * A}
CURRENT_COMPRESSION_RATIO = 1.75
EOM_REDUCTION = 10 * dB


class MOT(Fragment):
    """
    Methods for making and controlling the MOT

    If manual_init=True is passed to build_fragment, the user must call init()
    before this object is used
    """

    def build_fragment(self, manual_init=False):
        self.setattr_device("core")
        self.core: Core

        # Expose the loading time to ndscan
        self.loading_time: FloatParamHandle = self.setattr_param(
            "loading_time",
            FloatParam,
            "Time to load atoms for",
            default=DURATION["LOADING"],
            unit="s",
            min=0,
        )

        # Beam setters
        # Use the resetter ONLY for init/deinit
        self.beam_resetter: SetBeamsToDefaults = self.setattr_fragment(
            "beam_resetter",
            make_set_beams_to_default(
                suservo_beam_infos=SUServoedBeam[
                    "MOT",
                    "IMG",
                    "PUMP",
                    "LATX",
                    "LATY",
                    "CDT1",
                    "CDT2",
                ],
                name="beam_resetter",
            ),
        )
        self.all_beams: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "all_beams",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=SUServoedBeam[
                "MOT",
                "IMG",
                "PUMP",
                "LATX",
                "LATY",
                "CDT1",
                "CDT2",
            ],
        )
        self.mot_beam: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "mot_beam",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["MOT"]],
        )
        self.odt_beams: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "odt_beams",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=SUServoedBeam["CDT1", "CDT2"],
        )
        self.lattice_beams: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "lattice_beams",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=SUServoedBeam["LATX", "LATY"],
        )
        # EOM
        self.eom: EomFrag = self.setattr_fragment(
            "eom",
            EomFrag,
            Eom["repump"],
            init=False,
        )
        # Supplies
        self.coils: SetSupplies = self.setattr_fragment(
            "coils",
            SetSupplies,
            VDrivenSupply["X1", "X2", "Y", "Z"],
            init=False,
        )
        self.y_coil: SetSupplies = self.setattr_fragment(
            "y_coil",
            SetSupplies,
            VDrivenSupply["Y"],
            init=False,
        )
        self.push_780: SetSupplies = self.setattr_fragment(
            "push_780",
            SetSupplies,
            VDrivenSupply["push_780"],
            init=False,
        )
        self.unlock_ttl: TTLOut = self.get_device("780_unlock")

        # Ramps
        self._build_cmot()
        self._build_pgc()
        self._build_odt()

        self.debug_mode = logger.isEnabledFor(logging.DEBUG)
        self.manual_init = manual_init

        # Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "debug_mode",
            "manual_init",
        }

    def _build_cmot(self):
        """
        This function generates the ramp from MOT to CMOT
        It also creates parameters to expose to ndscan
        """
        self.CMOT_settle_time: FloatParamHandle = self.setattr_param(
            "CMOT_settle_time",
            FloatParam,
            "Time to wait after CMOT ramp",
            default=SETTLE_TIME["CMOT"],
            unit="ms",
            min=0 * ms,
        )
        self.CMOT_detuning: FloatParamHandle = self.setattr_param(
            "CMOT_detuning",
            FloatParam,
            "Detuning of the CMOT ramp",
            default=DETUNING["CMOT"],
            unit="Γ",
            scale=Γ_Rb,
        )

        class CMOT_Ramp(Ramp):
            """
            The transition from normal MOT to CMOT
                - MOT beam detuned red by unlock+push
                - Coils ramped up
                - Repump power ramped down
            """

            duration_default = DURATION["CMOT"]
            supplies = VDrivenSupply["X1", "X2", "push_780"]
            supplies_end = [
                VDrivenSupply["X1"].default_output * CURRENT_COMPRESSION_RATIO,
                VDrivenSupply["X2"].default_output * CURRENT_COMPRESSION_RATIO,
                self.CMOT_detuning,
            ]

            eoms = [Eom["repump"]]
            eom_att_end = [
                Eom["repump"].attenuation + EOM_REDUCTION,
            ]

        self.cmot_ramp: CMOT_Ramp = self.setattr_fragment(
            "cmot_ramp",
            CMOT_Ramp,
        )
        self.CMOT_duration: FloatParamHandle = self.setattr_param_rebind(
            "CMOT_duration",
            self.cmot_ramp,
            "duration",
            description="Duration of the CMOT ramp",
        )

    def _build_pgc(self):
        """
        This function generates the ramp from CMOT to PGC
        It also creates parameters to expose to ndscan
        """
        self.PGC_settle_time: FloatParamHandle = self.setattr_param(
            "PGC_settle_time",
            FloatParam,
            "Time to wait after PGC ramp",
            default=SETTLE_TIME["PGC"],
            unit="ms",
            min=0 * ms,
        )
        self.PGC_detuning: FloatParamHandle = self.setattr_param(
            "PGC_detuning",
            FloatParam,
            "Detuning of the PGC ramp",
            default=DETUNING["PGC"],
            unit="Γ",
            scale=Γ_Rb,
        )

        class PGC_Ramp(Ramp):
            """
            The transition from CMOT to PGC
                - MOT beam further detuned
                - Coils ramped back off
                - Bias ramped on
            """

            duration_default = DURATION["PGC"]

            supplies = VDrivenSupply[
                "X1",
                "X2",
                "Y",
                "Z",
                "push_780",
            ]
            supplies_start = [
                self.cmot_ramp,
                self.cmot_ramp,
                default,
                default,
                self.CMOT_detuning,
            ]
            supplies_end = [
                *BIASES.values(),
                self.PGC_detuning,
            ]

        self.pgc_ramp: PGC_Ramp = self.setattr_fragment(
            "pgc_ramp",
            PGC_Ramp,
        )
        self.PGC_duration: FloatParamHandle = self.setattr_param_rebind(
            "PGC_duration",
            self.pgc_ramp,
            "duration",
            description="Duration of the PGC ramp",
        )

    def _build_odt(self):
        """
        This function generates the ramp from the PGC to the ODT
        It also creates parameters to expose to ndscan
        """
        self.ODT_overlap_time: FloatParamHandle = self.setattr_param(
            "ODT_overlap_time",
            FloatParam,
            "Time to keep the ODT and MOT beams on together",
            default=100 * ms,
            unit="ms",
            min=0,
        )
        self.ODT_settle_time: FloatParamHandle = self.setattr_param(
            "ODT_settle_time",
            FloatParam,
            "Time to wait after ODT ramp",
            default=SETTLE_TIME["ODT"],
            unit="ms",
            min=0,
        )

        class ODT_Ramp(Ramp):
            """
            The transition from PGC to ODT
                - MOT ramped off
                - Bias ramped off
            """

            duration_default = DURATION["ODT"]
            supplies = VDrivenSupply["X1", "X2", "Y", "Z"]
            supplies_start = [self.pgc_ramp] * len(supplies)
            supplies_end = [0.0 * A] * len(supplies)

            suservos = [SUServoedBeam["MOT"]]
            suservo_setpoint_end = [0.0 * V]

        self.odt_ramp: ODT_Ramp = self.setattr_fragment(
            "odt_ramp",
            ODT_Ramp,
        )
        self.ODT_duration: FloatParamHandle = self.setattr_param_rebind(
            "ODT_duration",
            self.odt_ramp,
            "duration",
            description="Duration of the ODT ramp",
        )

    @kernel
    def device_setup(self):
        self.device_setup_subfragments()

        if not self.manual_init:
            self.core.break_realtime()
            self.init()

    @kernel
    def init(self) -> None:
        """
        Reset all state so we start deterministically:
        - Lasers off and reset
        - Eom defaulted
        - Coils defaulted
        - MOT locked and unpushed

        This is called automatically by device_setup unless `manual_init=True`
        was passed to build_fragment.

        **Timeline:** we break_realtime() after setting the devices
        """
        self.core.break_realtime()
        self.calculate_dma_handles()
        self.core.break_realtime()
        # Lasers set to defaults and turned off
        self.beam_resetter.turn_on_all(light_enabled=False)
        # EOM set to defaults
        self.eom.set_to_defaults()
        # Coils set to defaults
        self.coils.set_to_defaults()
        # MOT locked and unpushed
        self.relock_mot()

        self.core.break_realtime()

    @kernel
    def calculate_dma_handles(self):
        """
        Precalculate the DMA handles for the ramps

        No more DMA sequences may be recorded after this point
        """
        if self.debug_mode:
            logger.warning(
                "Calculating MOT ramp handles, "
                "No more DMA sequences may be recorded after this point"
            )
        self.core.break_realtime()
        self.cmot_ramp.precalculate_dma_handle()
        self.pgc_ramp.precalculate_dma_handle()
        self.odt_ramp.precalculate_dma_handle()

    @kernel
    def clear_atoms(self, clearout_time=100 * ms) -> None:
        """
        Clear out atoms from the MOT

        **Timeline:** advances by approx `clearout_time` seconds
        """
        self.y_coil.set_outputs([1.0 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()

    @kernel
    def load(self, clearout=True, clearout_time=1000 * ms, wait_for_load=True) -> None:
        """
        Load the MOT

        if `clearout` is True, ensure atoms are gone first

        **Timeline:** advances by approx `loading_time` seconds
        """
        if clearout:
            self.clear_atoms(clearout_time=clearout_time)

        self.mot_beam.turn_beams_on()

        if wait_for_load:
            delay(self.loading_time.get())

    @kernel
    def compress(self) -> None:
        """
        Compress into a CMOT

        **Timeline:** advances by `self.CMOT_duration` + `self.CMOT_settle_time`
        """
        with sequential:
            # Unlock the MOT
            self.unlock_mot()
            # Do the ramp - MOT freq, coil gradient, Eom attenuation
            self.cmot_ramp.do()
            # Fix EOM frequency
            self.eom.set_freq(self.eom.config.frequency + self.CMOT_detuning.get())

        # Wait for settle time
        delay(self.CMOT_settle_time.get())

    @kernel
    def pgc(self) -> None:
        """
        Cool further using Polarisation Gradient Cooling

        **Timeline:** advances by `self.PGC_duration` + `self.PGC_settle_time`
        """
        with sequential:
            # Do the ramp - MOT freq, coil to biases
            self.pgc_ramp.do()
            # Fix EOM frequency
            self.eom.set_freq(self.eom.config.frequency + self.PGC_detuning.get())

        # Wait for settle time
        delay(self.PGC_settle_time.get())

    @kernel
    def into_odt(self) -> None:
        """
        Load into the Optical Dipole Trap

        **Timeline:** advances by `self.ODT_duration` + `self.ODT_settle_time`
        """
        # ODT beam comes on and we let atoms transfer
        self.odt_beams.turn_beams_on()
        delay(self.ODT_overlap_time.get())
        # ramp off the MOT
        self.odt_ramp.do()

        # Fix up MOT ECDL for later imaging
        self.mot_beam.reset()
        with parallel:
            # Relock the MOT
            self.relock_mot()
            # Reset the EOM
            self.eom.set_to_defaults()

    @kernel
    def into_lattice(self) -> None:
        """
        Load into the Optical Lattice

        ramp on the lattice
        wait for settle time
        """
        raise NotImplementedError("How do we want to load the lattice?")

    @kernel
    def unlock_mot(self) -> None:
        """
        Unlock the MOT ECDL

        **Timeline:** advances by a single TTL write
        """
        self.unlock_ttl.on()

    @kernel
    def relock_mot(self, time_to_shift=1 * ms) -> None:
        """
        Relock the MOT ECDL

        Unpush and then after `time_to_shift` seconds, turn the TTL off

        **Timeline:** advances a single TTL+Fastino write

        However it writes the lock signal into the future by `time_to_shift`
        """
        self.push_780.set_to_defaults()
        delay(time_to_shift)
        self.unlock_ttl.off()
        delay(-time_to_shift)

    @kernel
    def drop(self) -> None:
        """
        Drop the MOT immediately

        Turn off all beams and coils

        We also relock the MOT to ensure the ECDL is in a known state
        """
        # Turn off beams
        self.all_beams.turn_beams_off()
        # Turn off the coils
        self.coils.turn_off()

        self.relock_mot()
