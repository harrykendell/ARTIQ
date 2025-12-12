from artiq.language.units import A, MHz, V, dB, ms
from ndscan.experiment import FloatParam, Fragment
from repository.models import Eom, Shutter, SUServoedBeam, VDrivenSupply
from repository.models.Device import device_arrays

EOMS = [
    Eom(
        name="repump",
        frequency=6580.0 * MHz,
        attenuation=17 * dB,
        mirny_ch="mirny_eom_repump",
        almazny_ch="almazny_eom_repump",
        almazny_enabled=True,
    ),
]
# Convert to dict for ease of use
EOMS = {eom.name: eom for eom in EOMS}

VDRIVEN_SUPPLIES = [
    VDrivenSupply(
        name="X1",
        fastino="fastino",
        ch=0,
        gain=2.0 * A / V,
        max_output=2.0 * A,
        default_output=0.0 * A,
    ),
    VDrivenSupply(
        name="X2",
        fastino="fastino",
        ch=1,
        gain=2.0 * A / V,
        max_output=2.0 * A,
        default_output=1.0 * A,
    ),
    VDrivenSupply(
        name="Y",
        fastino="fastino",
        ch=2,
        gain=2.0 * A / V,
        max_output=1.0 * A,
        default_output=0.0 * A,
    ),
    VDrivenSupply(
        name="Z",
        fastino="fastino",
        ch=3,
        gain=2.0 * A / V,
        max_output=1.0 * A,
        default_output=0.0 * A,
    ),
    VDrivenSupply(
        name="push_780",
        fastino="fastino",
        ch=4,
        gain=222 * MHz / V,
        min_output=-200 * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V
        max_output=200 * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V
        default_output=0.0 * MHz,
        unit="MHz",
    ),
    VDrivenSupply(
        name="push_852",
        fastino="fastino",
        ch=5,
        gain=83 * MHz / V,
        min_output=-300 * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V
        max_output=300 * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V
        default_output=0.0 * MHz,
        unit="MHz",
    ),
    # VDrivenSupply(
    #     name="GreenTA",
    #     fastino="fastino",
    #     ch=6,
    #     gain=0.4 * A / V,  # 4A max * V / 10V -> 0.4 A/V
    #     max_output=2.0 * A,
    #     default_output=1.450 * A,
    #     disabled=True,
    #     # TODO: Actually set me up
    # ),
    # VDrivenSupply(
    #     name="Dispenser",
    #     fastino="fastino",
    #     ch=7,
    #     gain=1.0 * A / V,
    #     max_output=3.0 * A,
    #     default_output=2.70 * A,
    #     disabled=True,
    #     # TODO: Actually set me up
    # ),
]
# Convert to dict for ease of use
VDRIVEN_SUPPLIES = {supply.name: supply for supply in VDRIVEN_SUPPLIES}

THORLABS_SHUTTER_DELAY = 35.0 * ms
EBAY_SHUTTER_DELAY = 25.0 * ms
# the switch on time is actually quick fast. The limit is the dislike of short pulses
SHUTTERS = [
    Shutter(
        name="MOT2D",
        ttl="shutter_2DMOT",
        delay=THORLABS_SHUTTER_DELAY,
    ),
    Shutter(
        name="MOT3D",
        ttl="shutter_3DMOT",
        delay=THORLABS_SHUTTER_DELAY,
    ),
    Shutter(
        name="CPT",
        ttl="shutter_LATTICE",
        delay=THORLABS_SHUTTER_DELAY,
    ),
]
# Convert to dict for ease of use
SHUTTERS = {beam.name: beam for beam in SHUTTERS}

SUSERVOED_BEAMS = [
    SUServoedBeam(
        name="Locking",
        frequency=198.0 * MHz,
        attenuation=17.0 * dB,
        suservo_device="suservo_aom_LOCK",
    ),
    SUServoedBeam(
        name="MOT",
        suservo_device="suservo_aom_MOT",
        frequency=192.0 * MHz,
        attenuation=17.0 * dB,
        shutter_device="shutter_3DMOT",
        shutter_delay=THORLABS_SHUTTER_DELAY,
        setpoint=3.5 * V,
        servo_enabled=True,
        calib_gain=21.83,
        calib_offset=0.037,
    ),
    SUServoedBeam(
        name="IMG",
        suservo_device="suservo_aom_IMG",
        frequency=198.0 * MHz,
        attenuation=18 * dB,
        # shutter_device="shutter_IMG",
        # shutter_delay=EBAY_SHUTTER_DELAY,
        setpoint=3.0 * V,
        servo_enabled=True,
        calib_gain=36.64e-3,
        calib_offset=-0.87e-3,
    ),
    SUServoedBeam(
        name="PUMP",
        suservo_device="suservo_aom_PUMP",
        frequency=205 * MHz,
        attenuation=18 * dB,
    ),
    SUServoedBeam(
        name="LATX",
        suservo_device="suservo_aom_LATX",
        frequency=197.95 * MHz,
        attenuation=17.0 * dB,
    ),
    SUServoedBeam(
        name="LATY",
        suservo_device="suservo_aom_LATY",
        frequency=200.0 * MHz,
        attenuation=18.5 * dB,
        shutter_device="shutter_LATTICE",
        shutter_delay=THORLABS_SHUTTER_DELAY,
    ),
    SUServoedBeam(
        name="CDT1",
        suservo_device="suservo_aom_CDT1",
        frequency=110.0 * MHz,
        attenuation=18.0 * dB,
        servo_enabled=True,
        calib_gain=14696.973513,
        calib_offset=-443.552294,
        setpoint=3.0 * V,  # 0.324 * V,
        # shutter_device="dummy_shutter",  # we don't have a shutter for this beam but need something to avoid errors
    ),
    SUServoedBeam(
        name="CDT2",
        suservo_device="suservo_aom_CDT2",
        frequency=110.0 * MHz,
        attenuation=18.0 * dB,
        servo_enabled=True,
        photodiode_offset=0.0115 * V,
        calib_gain=4251,
        calib_offset=-38.0,
        setpoint=3.4 * V,
        # shutter_device="dummy_shutter",  # we don't have a shutter for this beam but need something to avoid errors
    ),
]
# Convert to dict for ease of use
SUSERVOED_BEAMS = {beam.name: beam for beam in SUSERVOED_BEAMS}

# map from class to dict for initializing devices
device_arrays.update(
    {
        Eom: EOMS,
        VDrivenSupply: VDRIVEN_SUPPLIES,
        Shutter: SHUTTERS,
        SUServoedBeam: SUSERVOED_BEAMS,
        # Add other classes as needed
    }
)


class DefaultValues(Fragment):
    """
    This Fragment provides the global store for default values for all devices.
    This then allows them to be set in the GUI and scanned with a global source of truth.

    It must be added to the experiment's Fragment tree to be used:
    ```python
        DEVICE.fragment = frag.setattr_fragment("DefaultValues", DefaultValues)
    ```
    """

    def build_fragment(self):
        for eom in Eom.values():
            eom: Eom
            self.setattr_param(
                f"Eom_{eom.name}_frequency",
                FloatParam,
                f"Default frequency for Eom {eom.name}",
                default=eom.frequency,
                min=0.0,
                unit="MHz",
            )
            self.setattr_param(
                f"Eom_{eom.name}_attenuation",
                FloatParam,
                f"Default attenuation for Eom {eom.name}",
                default=eom.attenuation,
                min=0.0,
                max=31.5,
                unit="dB",
            )
        for sus in SUServoedBeam.values():
            sus: SUServoedBeam
            self.setattr_param(
                f"SUServoedBeam_{sus.name}_frequency",
                FloatParam,
                f"Default frequency for SUServoedBeam {sus.name}",
                default=sus.frequency,
                min=0.0,
                unit="MHz",
            )
            self.setattr_param(
                f"SUServoedBeam_{sus.name}_attenuation",
                FloatParam,
                f"Default attenuation for SUServoedBeam {sus.name}",
                default=sus.attenuation,
                min=0.0,
                max=31.5,
                unit="dB",
            )
            self.setattr_param(
                f"SUServoedBeam_{sus.name}_setpoint",
                FloatParam,
                f"Default setpoint for SUServoedBeam {sus.name}",
                default=sus.setpoint,
                min=0.0,
                unit="V",
            )
        for vds in VDrivenSupply.values():
            vds: VDrivenSupply
            self.setattr_param(
                f"VDrivenSupply_{vds.name}_default_output",
                FloatParam,
                f"Default output for VDrivenSupply {vds.name}",
                default=vds.default_output,
                unit=vds.unit,
            )
