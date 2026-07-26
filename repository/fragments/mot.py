import logging

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.language import delay, kernel, parallel
from artiq.language.units import A, MHz, V, dB, ms, s, us
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
from repository.fragments.ramp import Ramp
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import Eom, SUServoedBeam, VDrivenSupply

logger = logging.getLogger(__name__)

# Default constants - these can be overridden in the experiment
Γ_Rb = 6.065 * MHz  # Natural linewidth of Rb-87
DURATION = {
    "LOADING": 30 * s,
    "CMOT": 1.0 * ms,
    "PGC": 14.58 * ms,
    "EVAPORATION1": 50 * ms,
    "EVAPORATION2": 100 * ms,
}
SETTLE_TIME = {
    "CMOT": 0.522 * ms,
    "PGC": 4.98 * ms,
    "ODT": 0 * ms,
    "EVAPORATION1": 0 * ms,
    "EVAPORATION2": 0 * ms,
}
DETUNING = {"CMOT": 5 * Γ_Rb, "PGC": 9.94 * Γ_Rb}  # This is beyond the normal 2Γ
BIASES = {"X1": 0.0002 * A, "X2": 0.0 * A, "Y": 0.04 * A, "Z": 0.01 * A}
COMPRESSED_GRADIENTS = {"X1": 0 * A, "X2": 1.98 * A}
REPUMP_ATTENUATION = {"CMOT": 0.6196 * dB, "PGC": 0.05 * dB}
POWER_3D_MOT = {"MOT_loading": 3.5 * V, "CMOT": 1.9 * V, "PGC": 1.0 * V}


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

        # Beam SHUTTERS
        self.shutter_2d: TTLOut = self.get_device("shutter_2DMOT")
        self.cpt_shutter: TTLOut = self.get_device("shutter_LATTICE")
        # Use the resetter ONLY for init/deinit
        self.beam_resetter: SetBeamsToDefaults = self.setattr_fragment(
            "beam_resetter",
            make_set_beams_to_default(
                suservo_beam_infos=SUServoedBeam[
                    "MOT",
                    "IMG",
                    # "PUMP",
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
                # "PUMP",
                # "LATX",
                # "LATY",
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
        self.z_coil: SetSupplies = self.setattr_fragment(
            "z_coil",
            SetSupplies,
            VDrivenSupply["Z"],
            init=False,
        )

        self.push_780: SetSupplies = self.setattr_fragment(
            "push_780",
            SetSupplies,
            VDrivenSupply["push_780"],
            init=False,
        )

        self.PGC_Z_current: FloatParamHandle = self.setattr_param(
            "PGC_Z_current",
            FloatParam,
            "Bias current for the Z coil during PGC",
            default=BIASES["Z"],
            unit="A",
            min=0.0 * A,
            max=0.1 * A,
        )
        self.PGC_Y_current: FloatParamHandle = self.setattr_param(
            "PGC_Y_current",
            FloatParam,
            "Bias current for the Y coil during PGC",
            default=BIASES["Y"],
            unit="A",
            min=0.0 * A,
            max=0.1 * A,
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
            min=0.5 * ms,
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
            default=0,
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
            supplies = VDrivenSupply["X1", "X2", "push_780"]
            supplies_end = [
                COMPRESSED_GRADIENTS["X1"],  # X1
                COMPRESSED_GRADIENTS["X2"],  # X2
                self.CMOT_detuning,
            ]
            suservos = [SUServoedBeam["MOT"], SUServoedBeam["CDT2"]]
            suservo_setpoint_start = [POWER_3D_MOT["MOT_loading"], 0.0 * V]
            suservo_setpoint_end = [POWER_3D_MOT["CMOT"], 1.2 * V]

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
            min=0.0 * dB,
            max=14.0 * dB,
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
                "push_780",
            ]
            supplies_start = [
                BIASES["X1"],
                BIASES["X2"],
                self.CMOT_detuning,
            ]
            supplies_end = [
                BIASES["X1"],
                BIASES["X2"],
                self.PGC_detuning,
            ]
            suservos = [SUServoedBeam["MOT"]]
            suservo_setpoint_start = [POWER_3D_MOT["CMOT"]]
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

        class Evaporation_RAMP1(Ramp):
            # The transition from ODT to single beam evaporation
            # - ODT beams ramped off
            # - Single beam power ramped up

            duration_default = DURATION["EVAPORATION1"]

            suservos = [SUServoedBeam["CDT2"], SUServoedBeam["CDT1"]]
            suservo_setpoint_end = [0.0 * V, 0.0 * V]

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
        delay(100 * ms)  # we're hitting RTIO Underflows here?
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

        self.y_coil.set_outputs([0.7 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()

    @kernel
    def clear_atoms(self, clearout_time=100 * ms) -> None:
        """
        Clear out atoms from the MOT

        **Timeline:** advances by approx `clearout_time` seconds
        """

        # self.odt_dimple.off()
        self.y_coil.set_outputs([1.0 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()

    @kernel
    def load(self, clearout=True, clearout_time=1000 * ms, wait_for_load=True) -> None:
        """
        Load the MOT by turning on the MOT beams, assumes we are starting from the reset state

        if `clearout` is True, ensure atoms are gone first

        **Timeline:** advances by approx `loading_time` seconds
        """
        self.all_beams.off()
        # self.shutter_2d.on()

        # set detuning of the MOT suservo to some value that is not too far from the default, so that we can load atoms
        # self.suervoed_beam_mot = SUServoedBeam["MOT"]
        # self.suervoed_beam_mot.frequency

        if clearout:
            self.clear_atoms(clearout_time=clearout_time)

        self.mot_beam.on()
        # self.odt_reservoir.on()

        # We will check the MOT beam power after 10% of the loading time
        # so that it has settled in
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
        # Unlock the MOT
        TOPTICA_HOLD_JITTER = (
            150 * us
        )  # The Toptica PID only runs at 30kHz so give it time to hold
        delay(-TOPTICA_HOLD_JITTER)
        self.unlock_mot()
        delay(TOPTICA_HOLD_JITTER)

        # 2d shutter off to prevent push beam inteference
        self.shutter_2d.off()

        if evaporation_active or odt_active:
            # self.odt_dimple.on()
            self.odt_reservoir.on()

            # self.set_dimple_trap_power(power_dimple)
            self.set_reservoir_trap_power(power_reservoir)
        else:
            pass

        # if we are doing evaporation then only turn on the dimple and reservoir in cmot step
        # self.shutter_2d.off()
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
            self.cmot_ramp.do()
            delay(self.cmot_ramp.duration.get())

        delay(self.CMOT_settle_time.get())

    @kernel
    def pgc(self) -> None:
        """
        Cool further using Polarisation Gradient Cooling

        **Timeline:** advances by `self.PGC_duration` + `self.PGC_settle_time`
        """
        # Do the ramp - MOT freq, coil to biases
        # We must do these fastino writes in advance to avoid colliding with the ramp
        self.z_coil.set_outputs([self.PGC_Z_current.get()])
        self.y_coil.set_outputs([self.PGC_Y_current.get()])
        with parallel:
            # Fix EOM frequency
            self.eom.set_att(
                self.eom.config.attenuation + self.PGC_repump_attenuation.get()
            )
            self.eom.set_freq(
                self.eom.config.frequency
                + self.PGC_detuning.get()
                + self.PGC_repump_detuning.get()
            )
            self.pgc_ramp.do()

        delay(self.PGC_settle_time.get())

    @kernel
    def set_repump_attenuation(self, attenuation: float) -> None:
        """Set the repump EOM attenuation in dB"""
        self.eom.set_att(attenuation * dB)

    @kernel
    def evaporation1(self, single_step_evaporation) -> None:
        """
        Evaporate in the Optical Dipole Trap

        **Timeline:** advances by `self.evaporation.duration` + `self.evaporation.settle_time`
        """
        self.evaporation_ramp1.do()
        if single_step_evaporation:
            self.odt_dimple.off()
            self.odt_reservoir.off()

        delay(self.evaporation_settle_time1.get())

    @kernel
    def evaporation2(self) -> None:
        """
        Evaporate in the Optical Dipole Trap

        **Timeline:** advances by `self.evaporation.duration` + `self.evaporation.settle_time`
        """
        self.evaporation_ramp2.do()
        self.odt_dimple.off()
        self.odt_reservoir.off()

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
        self.push_780.set_to_defaults()
        delay(self.relock_duration.get())
        self.unlock_ttl.off()
        delay(-self.relock_duration.get())

    @kernel
    def drop(self, evaporation_active, odt_active) -> None:
        """
        Drop the MOT immediately
        Turn off all beams and coils
        We also relock the MOT to ensure the ECDL is in a known state
        """

        # Turn off the coils

        self.coils.turn_off()
        # self.shutter_2d.off()

        if evaporation_active or odt_active:
            self.mot_beam.off()
        else:
            self.all_beams.off()

        self.set_repump_attenuation(
            30 * dB
        )  # set repump to high attenuation so that we don't pump into F=2, imaging will be only F=2 to F'=3
        # For imaging we need to be back on resonance, only relock if we did cmot or pgc
        self.relock_mot()

    @kernel
    def pump_intoF2(self) -> None:
        """
        Set the repump EOM to go into F=2
        """
        self.eom.set_freq(6650 * MHz)
        delay(0.4 * ms)  # wait for EOM to shift

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
