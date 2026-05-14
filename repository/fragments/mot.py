import logging
 
from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.language import delay, kernel, parallel
from artiq.language.units import A, MHz, V, dB, ms, s, us
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
from repository.gui.managers import SUServoManager
 
 
logger = logging.getLogger(__name__)
 
# Default constants - these can be overridden in the experiment
Γ_Rb = 6.065 * MHz  # Natural linewidth of Rb-87
DURATION = {
    "LOADING": 30 * s,
    "CMOT": 30 * ms,
    "PGC": 20 * ms,
    "EVAPORATION1": 50 * ms,
    "EVAPORATION2": 100 * ms,
}
SETTLE_TIME = {
    "CMOT": 0.5 * ms,
    "PGC": 0.5 * ms,
    "ODT": 0 * ms,
    "EVAPORATION1": 0 * ms,
    "EVAPORATION2": 0 * ms,
}
DETUNING = {"CMOT": 5 * Γ_Rb, "PGC": 10 * Γ_Rb}  # This is beyond the normal 2Γ
BIASES = {"X1": 0.0002 * A, "X2": 0.0 * A, "Y": 0.04 * A, "Z": 0.07 * A}
COMPRESSED_GRADIENTS = {"X1": 0 * A, "X2": 1.98 * A}
REPUMP_ATTENUATION = {"CMOT": 9 * dB, "PGC": 0.5 * dB}
POWER_3D_MOT = {"MOT_loading": 3.5 * V, "CMOT": 3.5 * V, "PGC": 3.5 * V}
 
 
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
 
        self.push_780: SetSupplies = self.setattr_fragment(
            "push_780",
            SetSupplies,
            VDrivenSupply["push_780"],
            init=False,
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
        self.CMOT_Repump_power_attenuation: FloatParamHandle = self.setattr_param(
            "CMOT_Repump_power_attenuation",
            FloatParam,
            "Power of the CMOT Repump beam",
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
            suservo_setpoint_end = [1.9 * V, 1.2 * V]
 
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
                *BIASES.values(),
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
        self.lattice_beams.turn_beams_on()
        # EOM set to defaults
        self.eom.set_to_defaults()
        # Coils set to defaults
        self.coils.set_to_defaults()
        # MOT locked and unpushed
        self.relock_mot()
        self.core.break_realtime()
        # set ddipole and reservoir off
        self.odt_dimple.turn_beams_off()
        self.odt_reservoir.turn_beams_off()
 
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
    def clear_background_atoms_around_odt(self, clearout_time=0.5 * ms) -> None:
        """
        Clear out atoms from the background around the ODT
 
        **Timeline:** advances by approx `clearout_time` seconds
        """
 
        self.y_coil.set_outputs([1 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()
 
    @kernel
    def clear_atoms(self, clearout_time=100 * ms) -> None:
        """
        Clear out atoms from the MOT
 
        **Timeline:** advances by approx `clearout_time` seconds
        """
 
        # self.odt_dimple.turn_beams_off()
        self.y_coil.set_outputs([1.0 * A])
        delay(clearout_time)
        self.y_coil.set_to_defaults()
 
    @kernel
    def drop_dimple(self, clearout_time=0 * ms) -> None:
        """
        Clear out atoms from the ODT dimple
 
        **Timeline:** advances by approx `clearout_time` seconds
        """
        delay(clearout_time)
        self.odt_dimple.turn_beams_off()
 
    @kernel
    def on_dimple(self, clearout_time=0 * ms) -> None:
        """
        Clear out atoms from the ODT dimple
 
        **Timeline:** advances by approx `clearout_time` seconds
        """
        delay(clearout_time)
        self.odt_dimple.turn_beams_on()
 
    @kernel
    def drop_reservoir(self, clearout_time=0 * ms) -> None:
        """
        Clear out atoms from the ODT reservoir
 
        **Timeline:** advances by approx `clearout_time` seconds
        """
        delay(clearout_time)
        self.odt_reservoir.turn_beams_off()
 
    @kernel
    def on_reservoir(self, clearout_time=0 * ms) -> None:
        """
        Clear out atoms from the ODT reservoir
 
        **Timeline:** advances by approx `clearout_time` seconds
        """
        delay(clearout_time)
        self.odt_reservoir.turn_beams_on()
 
    @kernel
    def load(self, clearout=True, clearout_time=1000 * ms, wait_for_load=True) -> None:
        """
        Load the MOT by turning on the MOT beams, assumes we are starting from the reset state
 
        if `clearout` is True, ensure atoms are gone first
 
        **Timeline:** advances by approx `loading_time` seconds
        """
        self.all_beams.turn_beams_off()
        # self.shutter_2d.on()
 
        if clearout:
            self.clear_atoms(clearout_time=clearout_time)
 
        self.mot_beam.turn_beams_on()
        # self.odt_reservoir.turn_beams_on()
 
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
    def compress(self, evaporation_active, odt_active) -> None:
        """
        Compress into a CMOT
 
        **Timeline:** advances by `self.CMOT_duration` + `self.CMOT_settle_time`
        """
        # Unlock the MOT
        self.unlock_mot()
 
        if evaporation_active or odt_active:
            self.odt_dimple.turn_beams_on()
            # self.odt_reservoir.turn_beams_on()
            pass
 
        # if we are doing evaporation then only turn on the dimple and reservoir in cmot step
        # self.shutter_2d.off()
        with parallel:
            # Fix EOM frequency
            self.eom.set_freq(self.eom.config.frequency + self.CMOT_detuning.get())
            self.eom.set_att(
                self.eom.config.attenuation + self.CMOT_Repump_power_attenuation.get()
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
        with parallel:
            # Fix EOM frequency
            self.eom.set_freq(self.eom.config.frequency + self.PGC_detuning.get())
            self.pgc_ramp.do()
        
        delay(self.PGC_settle_time.get())
    
    @kernel
    def disable_repump(self) -> None:
        """Disable the repump EOM"""
        self.eom.disable()
 
    @kernel
    def enable_repump(self) -> None:
        """Enable the repump EOM"""
        self.eom.enable()
 
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
            self.odt_dimple.turn_beams_off()
            self.odt_reservoir.turn_beams_off()
            pass
        delay(self.evaporation_settle_time1.get())
 
    @kernel
    def evaporation2(self) -> None:
        """
        Evaporate in the Optical Dipole Trap
 
        **Timeline:** advances by `self.evaporation.duration` + `self.evaporation.settle_time`
        """
        self.evaporation_ramp2.do()
        self.odt_dimple.turn_beams_off()
        self.odt_reservoir.turn_beams_off()
 
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
    def relock_mot(self, time_to_shift=0.5 * ms) -> None:
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
    def drop(self, evaporation_active, odt_active, cmot_active, pgc_active) -> None:
        """
        Drop the MOT immediately
        Turn off all beams and coils
        We also relock the MOT to ensure the ECDL is in a known state
        """
 
        # Turn off the coils
        self.coils.turn_off()
 
        if evaporation_active or odt_active:
            self.mot_beam.turn_beams_off()
        else:
            self.all_beams.turn_beams_off()
 
        # For imaging we need to be back on resonance, only relock if we did cmot or pgc
        if cmot_active or pgc_active:
            self.relock_mot()
        else:
            pass
 
    @kernel
    def pump_intoF2(self) -> None:
        """
        Set the repump EOM to go into F=2
        """
        self.eom.set_freq(6650 * MHz)
        delay(0.4 * ms)  # wait for EOM to shift
 
    @kernel
    def turn_on_mot_beam(self) -> None:
        """
        Turn on the MOT beam only
        """
        self.mot_beam.turn_beams_on()
 
    @kernel
    def dipole_trap_com_shift(self) -> None:
        """
        Shift the dipole trap beams to a new position
        """
        self.evaporation_ramp1.do()
        # set odt reserviour to defalut setpoint
        # self.odt_reservoir.turn_beams_on()
 
    @kernel
    def set_dimple_trap_power(self, power_dimple=0.5) -> None:
        # set dds to particular power
        self.odt_dimple.set_setpoint_volts("CDT2", power_dimple)
 
    @kernel
    def set_reservoir_trap_power(self, power_reservoir=0.5) -> None:
        self.odt_reservoir.set_setpoint_volts("CDT1", power_reservoir)
 
    # get the setpoint of the dimple
    @kernel
    def get_dimple_trap_power(self, ch=6):
        print("Dimple trap power:", SUServoManager.SUServoManager.get_adc(ch))
        return SUServoManager.SUServoManager.get_adc(ch)
 
    # get the setpoint of the reservoir
    @kernel
    def get_reservoir_trap_power(self, ch=7):
        print("Reservoir trap power:", SUServoManager.SUServoManager.get_adc(ch))
        return SUServoManager.SUServoManager.get_adc(ch)
 
 