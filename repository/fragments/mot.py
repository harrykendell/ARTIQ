import logging
from typing import TYPE_CHECKING

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.language import delay, kernel, parallel
from artiq.language.units import A, MHz, V, dB, mA, ms, s, us
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import (
    FloatParam,
    FloatParamHandle,
)

from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.default_beam_setter import (
    SetBeamsToDefaults,
    make_set_beams_to_default,
)
from repository.fragments.eom_setter import EomFrag
from repository.fragments.ramp import LogRamp, Ramp
from repository.fragments.ramp import default as ramp_default
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import (
    THORLABS_SHUTTER_DELAY,
    Eom,
    SUServoedBeam,
    VDrivenSupply,
)

logger = logging.getLogger(__name__)

# rtio_log is an ARTIQ kernel-compiler builtin, not an importable Python symbol.
# Keep this declaration invisible at runtime so the kernel resolves the builtin.
if TYPE_CHECKING:

    def rtio_log(channel: str, *values: object) -> None: ...


# Default constants - these can be overridden in the experiment
Γ_Rb = 6.065 * MHz  # Natural linewidth of Rb-87
DURATION = {
    "LOADING": 30 * s,
    "CMOT": 0.85 * ms,
    "PGC": 10.0 * ms,
    "EVAPORATION1": 50 * ms,
    "EVAPORATION2": 100 * ms,
}
SETTLE_TIME = {
    "CMOT": 6.94 * ms,
    "PGC": 1.0 * ms,
    "ODT": 0 * ms,
    "EVAPORATION1": 0 * ms,
    "EVAPORATION2": 0 * ms,
}
DETUNING = {"CMOT": 9.65 * Γ_Rb, "PGC": 16 * Γ_Rb}  # Red detuning in units of Γ_Rb

# NB the LSB for the fastino is 0.305mA
# The ES030-10 LSB for programming is 0.61mA
CURRENT_LSB = 10 / 2**16 * A
BIASES_MOT = {
    "X_Bias": 0.45 * mA,
    "Y_Bias": 0.32 * mA,
    "Z_Bias": 45 * mA,
}
BIASES_CMOT = {
    "X_Bias": 0.45 * mA,
    "Y_Bias": 0.84 * mA,
    "Z_Bias": 59.8 * mA,
}
BIASES_PGC = {
    "X_Bias": 0.3 * mA,
    "Y_Bias": 0.32 * mA,
    "Z_Bias": 60 * mA,
}
# Working retained-atom/PGC baseline, RID33778. Higher 1.98 A CMOT lost atoms.
# The 1.0 A endpoint intentionally does not compress relative to MOT loading;
# a separate 0.6 -> 1.0 A loading-gradient test remains to be validated.
COMPRESSED_GRADIENT = {"X": 1.0 * A}
REPUMP_ATTENUATION = {"CMOT": 3.09 * dB, "PGC": 0.05 * dB}
POWER_3D_MOT = {"MOT_loading": 3.5 * V, "CMOT": 3.5 * V, "PGC": 2.0 * V}


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
        # Per-shot MOT controls. Neither modifies the device-level defaults;
        # the CMOT ramp uses the same values as its physical starting state.
        self.MOT_loading_gradient: FloatParamHandle = self.setattr_param(
            "MOT_loading_gradient",
            FloatParam,
            "X-gradient current during MOT loading",
            default=VDrivenSupply["X"].default_output,
            unit="A",
            min=0.6 * A,
            max=1.0 * A,
        )
        self.MOT_loading_setpoint: FloatParamHandle = self.setattr_param(
            "MOT_loading_setpoint",
            FloatParam,
            "MOT SUServo setpoint during MOT loading",
            default=POWER_3D_MOT["MOT_loading"],
            unit="V",
            min=1.5 * V,
            max=3.5 * V,
        )

        # Beam SHUTTERS
        self.shutter_2d: TTLOut = self.get_device("shutter_2DMOT")
        self.cpt_shutter: TTLOut = self.get_device("shutter_LATTICE")
        # Use the resetter ONLY for init/deinit
        self.beam_resetter: SetBeamsToDefaults = self.setattr_fragment(
            "beam_resetter",
            make_set_beams_to_default(
                suservo_beam_infos=SUServoedBeam[
                    "MOT",
                    "Imaging",
                    # "Pumping",
                    "Lattice_X",
                    "Lattice_Y",
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
                "Imaging",
                # "Pumping",
                # "Lattice_X",
                # "Lattice_Y",
                "CDT1",
                "CDT2",
            ],
        )
        self.mot_beam: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "mot_beam",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["MOT"]],
        )

        self.odt_reservoir: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "odt_reservoir",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["CDT1"]],
        )

        self.odt_dimple: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "odt_dimple",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["CDT2"]],
        )

        self.lattice_beams: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "lattice_beams",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=SUServoedBeam["Lattice_X", "Lattice_Y"],
        )

        self.seperate_repump: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "seperate_repump",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["Pumping"]],
        )

        # EOM
        self.eom: EomFrag = self.setattr_fragment(
            "eom",
            EomFrag,
            Eom["Repumping"],
            init=False,
        )
        self.MOT_EOM_frequency: FloatParamHandle = self.setattr_param(
            "MOT_EOM_frequency",
            FloatParam,
            "Repump EOM frequency at the start of each MOT load",
            default=Eom["Repumping"].frequency,
            unit="MHz",
            min=6300 * MHz,
            max=6800 * MHz,
        )

        self.MOT_frequency: FloatParamHandle = self.setattr_param(
            "MOT_frequency",
            FloatParam,
            "MOT AOM frequency",
            default=SUServoedBeam["MOT"].frequency,
            unit="MHz",
            min=150 * MHz,
            max=195 * MHz,
        )

        # Supplies
        self.coils: SetSupplies = self.setattr_fragment(
            "coils",
            SetSupplies,
            VDrivenSupply["X_Bias", "X", "Y_Bias", "Z_Bias"],
            init=False,
        )
        self.y_coil: SetSupplies = self.setattr_fragment(
            "y_coil",
            SetSupplies,
            VDrivenSupply["Y_Bias"],
            init=False,
        )
        self.z_coil: SetSupplies = self.setattr_fragment(
            "z_coil",
            SetSupplies,
            VDrivenSupply["Z_Bias"],
            init=False,
        )

        self.x_coil: SetSupplies = self.setattr_fragment(
            "x_coil",
            SetSupplies,
            VDrivenSupply["X_Bias"],
            init=False,
        )

        self.x_gradient_coil: SetSupplies = self.setattr_fragment(
            "x_gradient_coil",
            SetSupplies,
            VDrivenSupply["X"],
            init=False,
        )

        self.detune_780: SetSupplies = self.setattr_fragment(
            "Detuning_780",
            SetSupplies,
            VDrivenSupply["Detuning_780"],
            init=False,
        )

        # Y-Z BIAS CURRENTS
        self.MOT_Z_current: FloatParamHandle = self.setattr_param(
            "MOT_Z_current",
            FloatParam,
            "Bias current for the Z coil during MOT",
            default=BIASES_MOT["Z_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )
        self.MOT_Y_current: FloatParamHandle = self.setattr_param(
            "MOT_Y_current",
            FloatParam,
            "Bias current for the Y coil during MOT",
            default=BIASES_MOT["Y_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )

        self.MOT_X_current: FloatParamHandle = self.setattr_param(
            "MOT_X_current",
            FloatParam,
            "Bias current for the X coil during MOT",
            default=BIASES_MOT["X_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )

        self.CMOT_Z_current: FloatParamHandle = self.setattr_param(
            "CMOT_Z_current",
            FloatParam,
            "Bias current for the Z coil during CMOT",
            default=BIASES_CMOT["Z_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )
        self.CMOT_Y_current: FloatParamHandle = self.setattr_param(
            "CMOT_Y_current",
            FloatParam,
            "Bias current for the Y coil during CMOT",
            default=BIASES_CMOT["Y_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )

        self.CMOT_X_current: FloatParamHandle = self.setattr_param(
            "CMOT_X_current",
            FloatParam,
            "Bias current for the X coil during CMOT",
            default=BIASES_CMOT["X_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )

        self.PGC_Z_current: FloatParamHandle = self.setattr_param(
            "PGC_Z_current",
            FloatParam,
            "Bias current for the Z coil during PGC",
            default=BIASES_PGC["Z_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )
        self.PGC_Y_current: FloatParamHandle = self.setattr_param(
            "PGC_Y_current",
            FloatParam,
            "Bias current for the Y coil during PGC",
            default=BIASES_PGC["Y_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )

        self.PGC_X_current: FloatParamHandle = self.setattr_param(
            "PGC_X_current",
            FloatParam,
            "Bias current for the X coil during PGC",
            default=BIASES_PGC["X_Bias"],
            unit="mA",
            step=CURRENT_LSB,
            min=0.0 * A,
            max=0.5 * A,
        )

        self.power_dimple: FloatParamHandle = self.setattr_param(
            "power_dimple",
            FloatParam,
            "Power of the dimple trap",
            default=0.1 * V,
            unit="V",
            min=0.0 * V,
            max=15 * V,
        )
        self.power_reservoir: FloatParamHandle = self.setattr_param(
            "power_reservoir",
            FloatParam,
            "Power of the reservoir trap",
            default=0.1 * V,
            unit="V",
            min=0.0 * V,
            max=15 * V,
        )
        self.relock_duration: FloatParamHandle = self.setattr_param(
            "relock_duration",
            FloatParam,
            "Duration of the relock ramp",
            default=1.0 * ms,
            unit="ms",
            min=0.0 * ms,
        )

        self.unlock_ttl: TTLOut = self.get_device("780_unlock")

        # Opt-in low-gradient MOT settling before the CMOT light changes.
        # A zero hold bypasses this phase and retains the original CMOT ramp.
        self.pre_cmot_gradient: FloatParamHandle = self.setattr_param(
            "pre_cmot_gradient",
            FloatParam,
            "MOT field gradient during optional pre-CMOT settling",
            default=1.0 * A,
            unit="A",
            min=0.6 * A,
            max=1.0 * A,
        )
        self.pre_cmot_hold_time: FloatParamHandle = self.setattr_param(
            "pre_cmot_hold_time",
            FloatParam,
            "Hold at reduced MOT gradient before changing CMOT light; zero disables",
            default=0.0 * ms,
            unit="ms",
            min=0.0 * ms,
            max=50.0 * ms,
        )

        # Ramps
        self._build_cmot()
        self._build_pgc()
        self.build_evaporation1()
        self.build_evaporation2()

        self.debug_mode = logger.isEnabledFor(logging.INFO)
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
            min=0.0 * ms,
        )
        self.CMOT_detuning: FloatParamHandle = self.setattr_param(
            "CMOT_detuning",
            FloatParam,
            "Detuning of the CMOT ramp",
            default=DETUNING["CMOT"],
            unit="Γ",
            scale=Γ_Rb,
        )

        self.CMOT_repump_detuning: FloatParamHandle = self.setattr_param(
            "CMOT_repump_detuning",
            FloatParam,
            "Detuning of the CMOT Repump beam",
            default=0.075 * Γ_Rb,
            unit="Γ",
            scale=Γ_Rb,
        )

        self.CMOT_repump_attenuation: FloatParamHandle = self.setattr_param(
            "CMOT_repump_attenuation",
            FloatParam,
            "Attenuation of the CMOT Repump beam",
            default=REPUMP_ATTENUATION["CMOT"],
            unit="dB",
            min=0 * dB,
            max=14.0 * dB,
        )

        class PreCMOTGradientRamp(Ramp):
            """Change only the MOT gradient; keep MOT light, EOM and biases."""

            duration_default = 4.0 * ms
            supplies = [VDrivenSupply["X"]]
            supplies_start = [self.MOT_loading_gradient]
            supplies_end = [self.pre_cmot_gradient]

        self.pre_cmot_gradient_ramp: PreCMOTGradientRamp = self.setattr_fragment(
            "pre_cmot_gradient_ramp", PreCMOTGradientRamp
        )

        class CMOT_Ramp(Ramp):
            """
            The transition from normal MOT to CMOT
                - MOT beam detuned red by unlock+push
                - Coils ramped up
                - Repump power ramped down - but this must be done manually due to EOM issues
                - MOT power reduced
            """

            duration_default = DURATION["CMOT"]
            supplies = VDrivenSupply["X", "Detuning_780"]
            # Start from the current actually applied during MOT loading.
            supplies_start = [self.MOT_loading_gradient, ramp_default]
            supplies_end = [
                COMPRESSED_GRADIENT["X"],
                self.CMOT_detuning,
            ]
            suservos = [
                SUServoedBeam["MOT"],
                SUServoedBeam["CDT2"],
                SUServoedBeam["CDT1"],
            ]
            suservo_setpoint_start = [self.MOT_loading_setpoint, 0.0 * V, 0.0 * V]
            suservo_setpoint_end = [POWER_3D_MOT["CMOT"], 0.0 * V, 0.0 * V]

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

        class RelaxedCMOTRamp(CMOT_Ramp):
            """Normal CMOT endpoints, but begin from pre-CMOT gradient.

            The original CMOT ramp is retained for zero-hold experiments.
            Both CMOT ramps share endpoint handles (including ndscan scans).
            If scanning CMOT duration, set the relaxed-ramp duration as well.
            """

            supplies_start = [self.pre_cmot_gradient, ramp_default]
            supplies_end = [self.cmot_ramp.supplies_end_X, self.CMOT_detuning]
            suservo_setpoint_end = [
                self.cmot_ramp.suservo_setpoint_end_MOT,
                self.cmot_ramp.suservo_setpoint_end_CDT2,
                self.cmot_ramp.suservo_setpoint_end_CDT1,
            ]

        self.relaxed_cmot_ramp: RelaxedCMOTRamp = self.setattr_fragment(
            "relaxed_cmot_ramp", RelaxedCMOTRamp
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
            min=0.5 * ms,
        )
        self.PGC_detuning: FloatParamHandle = self.setattr_param(
            "PGC_detuning",
            FloatParam,
            "Detuning of the PGC ramp",
            default=DETUNING["PGC"],
            unit="Γ",
            scale=Γ_Rb,
        )

        self.PGC_repump_detuning: FloatParamHandle = self.setattr_param(
            "PGC_repump_detuning",
            FloatParam,
            "Detuning of the PGC Repump beam",
            default=0,
            unit="Γ",
            scale=Γ_Rb,
        )

        self.PGC_repump_attenuation: FloatParamHandle = self.setattr_param(
            "PGC_repump_attenuation",
            FloatParam,
            "Attenuation of the PGC Repump beam",
            default=REPUMP_ATTENUATION["PGC"],
            unit="dB",
            min=0 * dB,
            max=14.0 * dB,
        )

        # Experimental, opt-in EOM/repump timing modes. Mode 0 is the original
        # sequence; these parameters do not change any apparatus defaults.
        self.PGC_repump_timing_mode: FloatParamHandle = self.setattr_param(
            "PGC_repump_timing_mode",
            FloatParam,
            "PGC repump: 0 original; 1 freq 4ms; 2 freq 2-step; 3 att 4ms; 4 both 4ms",
            default=0.0,
            min=0.0,
            max=4.0,
        )

        class PGC_Ramp(Ramp):
            """
            The transition from CMOT to PGC
                - MOT beam further detuned
                - Coils ramped back off
                - Bias ramped on
            """

            duration_default = DURATION["PGC"]

            supplies = VDrivenSupply["X", "Detuning_780"]
            supplies_start = [self.cmot_ramp, self.CMOT_detuning]
            supplies_end = [0.0, self.PGC_detuning]
            suservos = [SUServoedBeam["MOT"]]
            suservo_setpoint_start = [self.cmot_ramp]
            suservo_setpoint_end = [POWER_3D_MOT["PGC"]]

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

    def build_evaporation1(self):
        # This function generates the ramp for single beam evaporation
        # It also creates parameters to expose to ndscan

        self.evaporation_duration1: FloatParamHandle = self.setattr_param(
            "evaporation_duration1",
            FloatParam,
            "Duration of the evaporation ramp 1",
            default=DURATION["EVAPORATION1"],
            unit="ms",
            min=0,
        )
        self.evaporation_settle_time1: FloatParamHandle = self.setattr_param(
            "evaporation_settle_time1",
            FloatParam,
            "Time to wait after evaporation ramp 1",
            default=SETTLE_TIME["EVAPORATION1"],
            unit="ms",
            min=0,
        )

        class Evaporation_RAMP1(LogRamp):
            # The transition from ODT to single beam evaporation
            # - ODT beams ramped off
            # - Single beam power ramped up

            duration_default = DURATION["EVAPORATION1"]

            suservos = [SUServoedBeam["CDT2"]]
            suservo_setpoint_start = [4.0 * V]
            suservo_setpoint_end = [0.01 * V]

        self.evaporation_ramp1: Evaporation_RAMP1 = self.setattr_fragment(
            "evaporation_ramp1",
            Evaporation_RAMP1,
        )

    def build_evaporation2(self):
        # This function generates the ramp for single beam evaporation
        # It also creates parameters to expose to ndscan

        self.evaporation_duration2: FloatParamHandle = self.setattr_param(
            "evaporation_duration2",
            FloatParam,
            "Duration of the evaporation ramp 2",
            default=DURATION["EVAPORATION2"],
            unit="ms",
            min=0,
        )
        self.evaporation_settle_time2: FloatParamHandle = self.setattr_param(
            "evaporation_settle_time2",
            FloatParam,
            "Time to wait after evaporation ramp 2",
            default=SETTLE_TIME["EVAPORATION2"],
            unit="ms",
            min=0,
        )

        class Evaporation_RAMP2(Ramp):
            # The transition from ODT to single beam evaporation
            # - ODT beams ramped off
            # - Single beam power ramped up

            duration_default = DURATION["EVAPORATION2"]

            suservos = [SUServoedBeam["CDT1"], SUServoedBeam["CDT2"]]
            suservo_setpoint_start = [1.0 * V, 3.0 * V]
            suservo_setpoint_end = [0.0 * V, 0.0 * V]

        self.evaporation_ramp2: Evaporation_RAMP2 = self.setattr_fragment(
            "evaporation_ramp2",
            Evaporation_RAMP2,
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
        self.reset()
        self.core.break_realtime()

    @kernel
    def reset(self) -> None:
        """
        Reset the MOT to a known state

        This is called automatically by device_setup unless `manual_init=True`
        was passed to build_fragment.

        **Timeline:** we break_realtime() after setting the devices
        """
        self.core.break_realtime()
        # Lasers set to defaults and turned off
        self.beam_resetter.turn_on_all(light_enabled=False)
        self.core.break_realtime()
        delay(
            THORLABS_SHUTTER_DELAY
        )  # we're hitting RTIO Underflows without this because beams.on() queues events in the past
        self.lattice_beams.on()
        # EOM set to defaults
        self.eom.set_to_defaults()
        # Coils set to defaults
        self.coils.set_to_defaults()
        # MOT locked and unpushed
        self.relock_mot()
        self.core.break_realtime()
        # set ddipole and reservoir off
        self.odt_dimple.off()
        self.odt_reservoir.off()

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
        self.pre_cmot_gradient_ramp.precalculate_dma_handle()
        self.relaxed_cmot_ramp.precalculate_dma_handle()
        self.pgc_ramp.precalculate_dma_handle()
        self.evaporation_ramp1.precalculate_dma_handle()
        self.evaporation_ramp2.precalculate_dma_handle()

        # safety check - EOMs take 400us to shift so we can't run faster than that
        if self.cmot_ramp.duration.get() < 400 * us:
            logger.warning(
                "CMOT ramp is too fast, "
                "EOMs will not have time to shift before the next operation"
            )
        if self.pgc_ramp.duration.get() + self.PGC_settle_time.get() < 400 * us:
            logger.warning(
                "PGC ramp is too fast, "
                "EOMs will not have time to shift before the next operation"
            )

    @kernel
    def clear_background_atoms_around_odt(self, clearout_time=3.0 * ms) -> None:
        """
        Clear out atoms from the background around the ODT

        **Timeline:** advances by approx `clearout_time` seconds
        """

        rtio_log("stage", "clearout:start")
        self.y_coil.set_outputs([0.7 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()
        rtio_log("stage", "clearout:end")

    @kernel
    def clear_atoms(self, clearout_time=100 * ms) -> None:
        """
        Clear out atoms from the MOT

        **Timeline:** advances by approx `clearout_time` seconds
        """

        # self.odt_dimple.off()
        rtio_log("stage", "clearout:start")
        self.y_coil.set_outputs([1.0 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()
        rtio_log("stage", "clearout:end")

    @kernel
    def set_starting_eom_frequency(self) -> None:
        """
        Set the repump EOM frequency for the start of this scan point.

        **Timeline:** advances by approx 400 us for the Mirny PLL relock.
        """
        self.eom.set_freq(self.MOT_EOM_frequency.get())
        delay(400 * us)

    @kernel
    def load(self, clearout=True, clearout_time=100 * ms, wait_for_load=True) -> None:
        """
        Load the MOT by turning on the MOT beams, assumes we are starting from the reset state

        if `clearout` is True, ensure atoms are gone first

        **Timeline:** advances by approx `loading_time` seconds
        """
        self.set_starting_eom_frequency()

        self.all_beams.off()
        # self.shutter_2d.on()

        # set detuning of the MOT suservo to some value that is not too far from the default, so that we can load atoms
        # self.suervoed_beam_mot = SUServoedBeam["MOT"]
        # self.suervoed_beam_mot.frequency

        if clearout:
            self.clear_atoms(clearout_time=clearout_time)

        # Apply both loading parameters on every shot, including reloads.
        # MOT.reset() restores the 1 A / 3.5 V device defaults beforehand.
        self.x_gradient_coil.set_outputs([self.MOT_loading_gradient.get()])
        self.mot_beam.set_setpoint_volts("MOT", self.MOT_loading_setpoint.get())

        # Mark optical loading, not the preceding EOM setup and atom clearout.
        # The load may continue in the caller when wait_for_load is False.
        rtio_log("stage", "load:start")
        self.mot_beam.on()
        # self.odt_reservoir.on()

        # We will check the MOT beam power after 10% of the loading time
        # so that it has settled in
        # set MOT bias coils
        self.z_coil.set_outputs([self.MOT_Z_current.get()])
        self.y_coil.set_outputs([self.MOT_Y_current.get()])
        self.x_coil.set_outputs([self.MOT_X_current.get()])
        if wait_for_load:
            delay(self.loading_time.get() / 10.0)
            if (
                self.mot_beam.beam_suservos[-1].get_y(
                    self.mot_beam.beam_suservos[-1].servo_channel
                )
                >= 0.99
            ):
                logger.warning("Insufficient power to the MOT beam")

            delay(9.0 * self.loading_time.get() / 10.0)

    @kernel
    def compress(
        self,
        evaporation_active,
        odt_active,
        power_dimple,
        power_reservoir,
    ) -> None:
        """
        Compress into a CMOT while turning off the push beam

        **Timeline:** advances by `self.CMOT_duration` + `self.CMOT_settle_time`
        """
        # MOT loading ends when the gradient transition begins. Keep ramp
        # and settled-field MOT illumination distinct in RTIO analysis.
        pre_cmot_active = self.pre_cmot_hold_time.get() > 0.0
        if pre_cmot_active:
            rtio_log("stage", "load:end")
            rtio_log("stage", "pre_cmot_ramp:start")
            self.pre_cmot_gradient_ramp.do()
            rtio_log("stage", "pre_cmot_ramp:end")
            rtio_log("stage", "pre_cmot_hold:start")
            delay(self.pre_cmot_hold_time.get())

        # The original Toptica hold command precedes the nominal CMOT
        # boundary by 150 us. Place the boundary logs at the actual command
        # time (after the rewind) rather than 150 us in its future.
        TOPTICA_HOLD_JITTER = (
            150 * us
        )  # The Toptica PID only runs at 30kHz so give it time to hold
        delay(-TOPTICA_HOLD_JITTER)
        if pre_cmot_active:
            rtio_log("stage", "pre_cmot_hold:end")
        else:
            rtio_log("stage", "load:end")
        rtio_log("stage", "compress:start")
        self.unlock_mot()

        # 2d shutter off to prevent push beam inteference
        self.shutter_2d.off()

        if evaporation_active or odt_active:
            self.odt_dimple.on()
            self.odt_reservoir.on()
            # CDT overlaps the cooling and evaporation stages.
            rtio_log("stage", "cdt:start")

        # if we are doing evaporation then only turn on the dimple and reservoir in cmot step
        # self.set_dimple_trap_power(power_dimple)
        # self.set_reservoir_trap_power(power_reservoir)

        # set CMOT bias coils
        self.z_coil.set_outputs([self.CMOT_Z_current.get()])
        self.y_coil.set_outputs([self.CMOT_Y_current.get()])
        self.x_coil.set_outputs([self.CMOT_X_current.get()])
        with parallel:
            # Fix EOM frequency
            self.eom.set_freq(
                self.eom.config.frequency
                + self.CMOT_detuning.get()
                + self.CMOT_repump_detuning.get()
            )
            self.eom.set_att(
                self.eom.config.attenuation + self.CMOT_repump_attenuation.get()
            )
            if self.pre_cmot_hold_time.get() > 0.0:
                self.relaxed_cmot_ramp.do()
                delay(self.relaxed_cmot_ramp.duration.get())
            else:
                self.cmot_ramp.do()
                delay(self.cmot_ramp.duration.get())

        delay(self.CMOT_settle_time.get())
        rtio_log("stage", "compress:end")

    @kernel
    def _pgc_repump_frequency_timing(self) -> None:
        """Opt-in repump-frequency trajectory within the unchanged 8 ms PGC."""
        mode = self.PGC_repump_timing_mode.get()
        final_freq = (
            self.eom.config.frequency
            + self.PGC_detuning.get()
            + self.PGC_repump_detuning.get()
        )
        if mode < 1.5:
            # Retain CMOT EOM frequency until 4 ms, then jump to final PGC.
            delay(4 * ms)
            self.eom.set_freq(final_freq)
        elif mode < 2.5:
            # Follow the optical ramp more closely with two PLL-safe updates.
            # The PLL call advances the RTIO timeline by approximately 400 us;
            # the final jump occurs at approximately 5.9 ms (< 8 ms).
            delay(2 * ms)
            self.eom.set_freq(
                self.eom.config.frequency
                + 0.5 * (self.CMOT_detuning.get() + self.PGC_detuning.get())
                + 0.5
                * (self.CMOT_repump_detuning.get() + self.PGC_repump_detuning.get())
            )
            delay(3.5 * ms)
            self.eom.set_freq(final_freq)
        elif mode < 3.5:
            # Same frequency command time as historical PGC.
            self.eom.set_freq(final_freq)
        else:
            delay(4 * ms)
            self.eom.set_freq(final_freq)

    @kernel
    def _pgc_repump_attenuation_timing(self) -> None:
        """Keep CMOT repump attenuation for 4 ms in modes 3 and 4."""
        if self.PGC_repump_timing_mode.get() >= 2.5:
            delay(4 * ms)
        self.eom.set_att(
            self.eom.config.attenuation + self.PGC_repump_attenuation.get()
        )

    @kernel
    def pgc(self) -> None:
        """
        Cool further using Polarisation Gradient Cooling

        **Timeline:** advances by `self.PGC_duration` + `self.PGC_settle_time`
        """
        rtio_log("stage", "pgc:start")
        # Preserve original immediate Fastino bias steps and 8 ms gradient ramp.
        self.x_coil.set_outputs([self.PGC_X_current.get()])
        self.z_coil.set_outputs([self.PGC_Z_current.get()])
        self.y_coil.set_outputs([self.PGC_Y_current.get()])
        if self.PGC_repump_timing_mode.get() < 0.5:
            # Mode 0 is byte-for-byte the original parallel EOM/optical ramp.
            with parallel:
                self.eom.set_att(
                    self.eom.config.attenuation + self.PGC_repump_attenuation.get()
                )
                self.eom.set_freq(
                    self.eom.config.frequency
                    + self.PGC_detuning.get()
                    + self.PGC_repump_detuning.get()
                )
                self.pgc_ramp.do()
        else:
            if self.PGC_duration.get() < 7.5 * ms or self.PGC_duration.get() > 8.5 * ms:
                raise ValueError("Experimental repump timing requires 8 ms PGC")
            # Schedule immediate SPI operations and the ramp DMA before
            # backdated branches containing delayed EOM writes. This avoids
            # unnecessarily scheduling earlier RTIO timestamps after longer
            # on-core PLL operations.
            mode = self.PGC_repump_timing_mode.get()
            if mode < 2.5:
                # Immediate attenuation; delayed frequency (modes 1/2).
                with parallel:
                    self._pgc_repump_attenuation_timing()
                    self.pgc_ramp.do()
                    self._pgc_repump_frequency_timing()
            elif mode < 3.5:
                # Immediate frequency; delayed attenuation (mode 3).
                with parallel:
                    self._pgc_repump_frequency_timing()
                    self.pgc_ramp.do()
                    self._pgc_repump_attenuation_timing()
            else:
                # Both EOM changes delayed (mode 4).
                with parallel:
                    self.pgc_ramp.do()
                    self._pgc_repump_attenuation_timing()
                    self._pgc_repump_frequency_timing()
        delay(self.PGC_settle_time.get())
        rtio_log("stage", "pgc:end")

    @kernel
    def set_repump_attenuation(self, attenuation: float) -> None:
        """Set the repump EOM attenuation in dB"""
        self.eom.set_att(attenuation * dB)

    @kernel
    def set_repum_attenuation_default(self):
        """Set the repump EOM attenuation in dB"""
        self.eom.default_att()

    @kernel
    def evaporation1(self, single_step_evaporation) -> None:
        """
        Evaporate in the Optical Dipole Trap

        **Timeline:** advances by `self.evaporation.duration` + `self.evaporation.settle_time`
        """
        rtio_log("stage", "hold:end")
        rtio_log("stage", "evaporation:start")
        # self.x_gradient_coil.set_outputs([1.9*A])
        self.evaporation_ramp1.do()
        if single_step_evaporation:
            # The atoms are released at trap extinction, before the settle delay.
            rtio_log("stage", "evaporation:end")
            self.release_cdt(mark_hold_end=False)

        delay(self.evaporation_settle_time1.get())

    @kernel
    def evaporation2(self) -> None:
        """
        Evaporate in the Optical Dipole Trap

        **Timeline:** advances by `self.evaporation.duration` + `self.evaporation.settle_time`
        """
        self.evaporation_ramp2.do()
        rtio_log("stage", "evaporation:end")
        self.release_cdt(mark_hold_end=False)

    @kernel
    def switch_off_cdt(self) -> None:
        """Turn off both CDT beams and close their independent RTIO stage."""
        self.odt_dimple.off()
        self.odt_reservoir.off()
        rtio_log("stage", "cdt:end")

    @kernel
    def release_cdt(self, mark_hold_end=True) -> None:
        """Release trapped atoms and mark the start of time of flight.

        CDT-only release ends the hold here; evaporation ended the hold at
        the start of evaporation, so do not log an unmatched second end.
        """
        self.switch_off_cdt()
        if mark_hold_end:
            rtio_log("stage", "hold:end")
        rtio_log("stage", "expansion:start")

    @kernel
    def mark_imaging_start(self) -> None:
        """Mark the start of absorption image acquisition."""
        rtio_log("stage", "imaging:start")

    @kernel
    def mark_imaging_end(self) -> None:
        """Mark the end of absorption image acquisition."""
        rtio_log("stage", "imaging:end")

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
    def relock_mot(self) -> None:
        """
        Relock the MOT ECDLImmediately reset detuning then after `relock_duration` reset the TTL to off so the PID continues

        **Timeline:** does not advance the timeline

        However it writes the ramp and TTL into the future by `relock_duration`
        """
        self.detune_780.set_to_defaults()
        delay(self.relock_duration.get())
        self.unlock_ttl.off()
        delay(-self.relock_duration.get())

    @kernel
    def drop(self, evaporation_active, odt_active, sideband=False) -> None:
        """
        Drop the MOT immediately
        Turn off all beams and coils
        We also relock the MOT to ensure the ECDL is in a known state
        Here we can trun on and off sideband by turing on and off sideband, if we want sideband in imaging or not
        """

        # Loading is closed at MOT light extinction in MOT-only acquisitions.
        # When CMOT ran already, this end marker is harmlessly unmatched.
        # Turn off the coils

        self.coils.turn_off()
        # self.shutter_2d.off()

        if evaporation_active or odt_active:
            self.mot_beam.off()
            rtio_log("stage", "load:end")
            # The MOT is off but the CDT continues to hold the atoms.
            rtio_log("stage", "hold:start")
        else:
            self.all_beams.off()
            rtio_log("stage", "load:end")
            # In the absence of a trap, MOT extinction releases the atoms.
            rtio_log("stage", "expansion:start")

        # self.set_repump_attenuation(
        #     30 * dB
        # )  # set repump to high attenuation so that we don't pump into F=2, imaging will be only F=2 to F'=3
        # For imaging we need to be back on resonance, only relock if we did cmot or pgc
        if sideband:
            self.Enable_EOM()
        else:
            self.Disable_EOM()

        self.relock_mot()

    @kernel
    def Disable_EOM(self) -> None:
        """
        Set the repump EOM to go into F=2
        """
        self.eom.disable()

    @kernel
    def Enable_EOM(self) -> None:
        """
        Set the repump EOM to go into F=2
        """
        self.eom.disable()

    @kernel
    def dipole_trap_com_shift(self) -> None:
        """
        Shift the dipole trap beams to a new position
        """
        self.evaporation_ramp1.do()
        # set odt reserviour to defalut setpoint
        # self.odt_reservoir.on()

    @kernel
    def set_dimple_trap_power(self, power_dimple=0.5) -> None:
        # set dds to particular power
        self.odt_dimple.set_setpoint_volts("CDT2", power_dimple)

    @kernel
    def set_reservoir_trap_power(self, power_reservoir=0.5) -> None:
        self.odt_reservoir.set_setpoint_volts("CDT1", power_reservoir)

    @kernel
    def set_mot_frequency(self, frequency_mhz) -> None:
        """Set the MOT beam AOM frequency in MHz without changing its setpoint."""
        mot_suservo = self.mot_beam.beam_suservos[0]
        mot_beam_info = self.mot_beam.beam_infos[0]
        mot_suservo.set_dds(
            profile=mot_suservo.servo_channel,
            frequency=frequency_mhz * MHz,
            offset=-1.0 * mot_beam_info.setpoint / 10.0,
        )

    @kernel
    def turn_on_mot(self):
        self.mot_beam.on()

    @kernel
    def turn_off_mot(self):
        self.mot_beam.off()
