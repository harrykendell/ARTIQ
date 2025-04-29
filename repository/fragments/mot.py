import logging

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.language import delay, kernel, sequential, parallel
from artiq.language.units import s, ms, MHz, dB, A
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import FloatParam, FloatParamHandle
from repository.fragments.default_beam_setter import (
    SetBeamsToDefaults,
    make_set_beams_to_default,
)
from repository.fragments.eom_setter import EomFrag
from repository.fragments.supply_setter import SetSupplies
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM

from repository.models.devices import SUServoedBeam, Eom, VDrivenSupply
from repository.fragments.ramp import Ramp

logger = logging.getLogger(__name__)


class MOT(Fragment):
    """
    Methods for making and controlling the MOT

    If manual_init=True is passed to build_fragment, the user must call init()
    before this object is used
    """

    def build_fragment(self, manual_init=False):
        self.setattr_device("core")
        self.core: Core

        self.state = self.State.UNINITIALIZED

        self.unlock_ttl: TTLOut = self.get_device("780_unlock")

        # Useful params for the MOT
        self.loading_time: FloatParamHandle = self.setattr_param(
            "loading_time",
            FloatParam,
            "Time to load atoms for",
            default=20 * s,
            unit="s",
            min=0,
        )
        self.clearout_time: FloatParamHandle = self.setattr_param(
            "clearout_time",
            FloatParam,
            "Time to allow for atoms to clearout",
            default=100 * ms,
            unit="ms",
            min=0,
        )

        # Beams
        self.beam_resetter: SetBeamsToDefaults = self.setattr_fragment(
            "beam_resetter",
            make_set_beams_to_default(
                suservo_beam_infos=SUServoedBeam.all(), name="beam_resetter"
            ),
            "Set the beams to their default values",
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
        #  EOM
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
        self.x_coils: SetSupplies = self.setattr_fragment(
            "x_coils",
            SetSupplies,
            VDrivenSupply["X1", "X2"],
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
            [VDrivenSupply["push_780"]],
            init=False,
        )

        # Compression ramp
        self.CMOT_detuning: FloatParamHandle = self.setattr_param(
            "cmot_detuning",
            FloatParam,
            "Detuning red of nominal of the MOT beam during CMOT",
            default=10 * MHz,
            unit="MHz",
            min=0,
        )
        self.CMOT_compression_ratio: FloatParamHandle = self.setattr_param(
            "CMOT_compression_ratio",
            FloatParam,
            "Ratio to increase the X1 and X2 coils current by",
            default=1.75,
            unit="ratio",
            min=0.0,
        )
        self.CMOT_eom_reduction: FloatParamHandle = self.setattr_param(
            "CMOT_eom_reduction",
            FloatParam,
            "Attenuation to reduce the EOM by",
            default=10 * dB,
            unit="dB",
            min=0 * dB,
        )

        class CMOT_Ramp(Ramp):
            """
            The transition from normal MOT to CMOT
                - MOT beam detuned red by unlock+push
                - Coils ramped up
                - Repump power ramped down
            """

            duration_default = 1 * ms
            supplies = VDrivenSupply["X1", "X2", "push_780"]
            supplies_end = [
                VDrivenSupply["X1"].default_output * self.CMOT_compression_ratio.get(),
                VDrivenSupply["X2"].default_output * self.CMOT_compression_ratio.get(),
                self.CMOT_detuning.get(),
            ]

            eoms = [Eom["repump"]]
            eom_att_end = [
                Eom["repump"].attenuation + self.CMOT_eom_reduction.get(),
            ]

        self.cmot_ramp: CMOT_Ramp = self.setattr_fragment(
            "cmot_ramp",
            CMOT_Ramp,
        )
        self.CMOT_duration: FloatParamHandle = self.setattr_param_rebind(
            "CMOT_duration",
            self.cmot_ramp,
            "default_duration",
            description="Duration of the CMOT ramp",
        )
        self.CMOT_settle_time: FloatParamHandle = self.setattr_param(
            "CMOT_settle_time",
            FloatParam,
            "Time to wait after CMOT ramp",
            default=10 * ms,
            unit="ms",
            min=0,
        )

        # PGC ramp
        self.PGC_detuning: FloatParamHandle = self.setattr_param(
            "PGC_detuning",
            FloatParam,
            "Detuning red of nominal for the MOT beam during PGC",
            default=60.65 * MHz,
            unit="MHz",
            min=0,
        )
        self.X1_bias: FloatParamHandle = self.setattr_param(
            "X1_bias",
            FloatParam,
            "Bias to apply to the coil during PGC",
            default=0.0 * A,
            unit="A",
            min=0.0 * A,
        )
        self.X2_bias: FloatParamHandle = self.setattr_param_like(
            "X2_bias", self, default=0.0
        )
        self.Y_bias: FloatParamHandle = self.setattr_param_like(
            "Y_bias", self, default=0.0
        )
        self.Z_bias: FloatParamHandle = self.setattr_param_like(
            "Z_bias", self, default=0.0
        )

        class PGC_Ramp(Ramp):
            """
            The transition from CMOT to PGC
                - MOT beam further detuned
                - Coils ramped back off
                - Bias ramped on
            """

            duration_default = 1 * ms

            supplies = VDrivenSupply["X1", "X2", "Y", "Z", "push_780"]
            supplies_start = [
                VDrivenSupply["X1"].default_output * self.CMOT_compression_ratio.get(),
                VDrivenSupply["X2"].default_output * self.CMOT_compression_ratio.get(),
                VDrivenSupply["Y"].default_output,
                VDrivenSupply["Z"].default_output,
                self.CMOT_detuning.get(),
            ]
            supplies_end = [
                self.X1_bias.get(),
                self.X2_bias.get(),
                self.Y_bias.get(),
                self.Z_bias.get(),
                self.PGC_detuning.get(),
            ]

        self.pgc_ramp: PGC_Ramp = self.setattr_fragment(
            "pgc_ramp",
            PGC_Ramp,
        )
        self.PGC_duration: FloatParamHandle = self.setattr_param_rebind(
            "PGC_duration",
            self.pgc_ramp,
            "default_duration",
            description="Duration of the PGC ramp",
        )
        self.PGC_settle_time: FloatParamHandle = self.setattr_param(
            "PGC_settle_time",
            FloatParam,
            "Time to wait after PGC ramp",
            default=3 * ms,
            unit="ms",
            min=0,
        )

        class ODT_Ramp(Ramp):
            """
            The transition from PGC to ODT
                - MOT ramped off
                - Bias ramped off
            """

            duration_default = 1 * ms
            supplies = VDrivenSupply["X1", "X2", "Y", "Z"]
            supplies_start = [
                self.X1_bias.get(),
                self.X2_bias.get(),
                self.Y_bias.get(),
                self.Z_bias.get(),
            ]
            supplies_end = [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ]

            suservos = [SUServoedBeam["MOT"]]
            suservo_setpoint_end = [0.0]

            pass

        self.odt_ramp: ODT_Ramp = self.setattr_fragment(
            "odt_ramp",
            ODT_Ramp,
        )
        self.ODT_overlap_time: FloatParamHandle = self.setattr_param(
            "ODT_overlap_time",
            FloatParam,
            "Time to keep the ODT and MOT beams on together",
            default=100 * ms,
            unit="ms",
            min=0,
        )
        self.ODT_duration: FloatParamHandle = self.setattr_param_rebind(
            "ODT_duration", self.odt_ramp, "default_duration"
        )
        self.ODT_settle_time: FloatParamHandle = self.setattr_param(
            "ODT_settle_time",
            FloatParam,
            "Time to wait after ODT ramp",
            default=100 * ms,
            unit="ms",
            min=0,
        )

        self.debug_mode = logger.isEnabledFor(logging.DEBUG)
        self.manual_init = manual_init

        # Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {"debug_mode", "manual_init"}

    @kernel
    def device_setup(self):
        self.device_setup_subfragments()

        if not self.manual_init:
            self.core.break_realtime()
            self.calculate_dma_handles()
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
        logger.warning(
            "Calculating MOT ramp handles, "
            "No more DMA sequences may be recorded after this point"
        )
        self.cmot_ramp.precalculate_dma_handle()
        self.pgc_ramp.precalculate_dma_handle()
        self.odt_ramp.precalculate_dma_handle()

    @kernel
    def clear_atoms(self) -> None:
        """
        Clear out atoms from the MOT

        **Timeline:** advances by approx `clearout_time` seconds
        """
        raise NotImplementedError("How do we want to clear out atoms?")
        delay(self.clearout_time.get())

    @kernel
    def load(self, clearout=True) -> None:
        """
        Load the MOT

        if `clearout` is True, ensure atoms are gone first

        **Timeline:** advances by approx `loading_time` seconds
        """
        if clearout:
            self.clear_atoms()

        self.mot_beam.turn_beams_on()

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
            # Do the ramp - MOT freq, coil biases
            self.pgc_ramp.do()
            # Fix EOM frequency
            self.eom.set_freq(self.eom.config.frequency + self.PGC_detuning.get())

        # Wait for settle time
        delay(self.PGC_settle_time.get())

    @kernel
    def into_odt(self) -> None:
        """
        Load into the Optical Dipole Trap

        ramp on the ODT
        wait for overlap time
        ramp the MOT off and reset:
            - MOT beam off
            - unpush
            - relock
            - reset EOM freq/att
            - turn off coils
        """
        with sequential:
            # ODT beam comes on and we let atoms transfer
            self.odt_beams.turn_beams_on()
            delay(self.ODT_overlap_time.get())
            # ramp off the MOT
            self.odt_ramp.do()

            # Turn off the MOT beam
            self.mot_beam.turn_beams_off()

        # Fix up ECDL for later imaging
        with parallel:
            # Relock the MOT
            self.relock_mot()
            # Reset the EOM frequency
            self.eom.set_freq(self.eom.config.frequency)

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

        **Timeline:** advances by `time_to_shift` and a single TTL+Fastino write
        """
        self.push_780.set_to_defaults()
        delay(time_to_shift)
        self.unlock_ttl.off()

    @kernel
    def drop(self) -> None:
        """
        Drop the MOT immediately

        Turn off all beams and coils
        """
        with parallel:
            # Turn off beams
            self.mot_beam.turn_beams_off()
            self.odt_beams.turn_beams_off()
            self.lattice_beams.turn_beams_off()
            # Turn off the coils
            self.coils.set_outputs([0.0] * len(self.coils.supplies))
