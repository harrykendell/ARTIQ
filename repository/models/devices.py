from repository.models import CoilPair, Eom, Shutter, SUServoedBeam, VDrivenSupply
from repository.models.Device import device_arrays
from artiq.language.units import ms, dB, MHz, V, A

EOMS = [
    Eom(
        name="repump_eom",
        frequency=3285.0 * MHz,
        attenuation=10.0 * dB,
        mirny_ch="mirny_eom_repump",
        almazny_ch="almazny_eom_repump",
        mirny_enabled=True,
    )
]
# Convert to dict for ease of use
EOMS = {eom.name: eom for eom in EOMS}

VDRIVEN_SUPPLIES = [
    VDrivenSupply(
        name="X1",
        fastino="fastino",
        ch=0,
        gain=2.0 * A / V,
        current_limit=3.0 * A,
        default_current=0.9 * A,
    ),
    VDrivenSupply(
        name="X2",
        fastino="fastino",
        ch=1,
        gain=2.0 * A / V,
        current_limit=3.0 * A,
        default_current=1.2 * A,
    ),
    VDrivenSupply(
        name="Y",
        fastino="fastino",
        ch=2,
        gain=2.0 * A / V,
        current_limit=3.0 * A,
        default_current=0.0 * A,
    ),
    VDrivenSupply(
        name="Z",
        fastino="fastino",
        ch=3,
        gain=2.0 * A / V,
        current_limit=3.0 * A,
        default_current=0.0 * A,
    ),
    VDrivenSupply(
        name="GreenTA",
        fastino="fastino",
        ch=6,
        gain=0.4 * A / V,  # 4A max * V / 10V -> 0.4 A/V
        current_limit=2.0 * A,
        default_current=1.450 * A,
        # TODO: Actually set me up
    ),
    VDrivenSupply(
        name="Dispenser",
        fastino="fastino",
        ch=7,
        gain=0.0 * A / V,
        current_limit=3.0 * A,
        default_current=2.70 * A,
        # TODO: Actually set me up
    ),
]
# Convert to dict for ease of use
VDRIVEN_SUPPLIES = {supply.name: supply for supply in VDRIVEN_SUPPLIES}

COIL_PAIRS = [
    CoilPair(
        name="X",
        coil1="X1",
        coil2="X2",
        default_current_comm=1.0 * A,
        default_current_diff=1.0 * A,
    ),
]
# Convert to dict for ease of use
COIL_PAIRS = {pair.name: pair for pair in COIL_PAIRS}

THORLABS_SHUTTER_DELAY = 35.0 * ms
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
        frequency=193.0 * MHz,
        attenuation=17.0 * dB,
        shutter_device="shutter_3DMOT",
        shutter_delay=THORLABS_SHUTTER_DELAY,
        setpoint=2.5 * V,
        servo_enabled=True,
        calib_gain=21.83,
        calib_offset=0.037,
    ),
    SUServoedBeam(
        name="IMG",
        suservo_device="suservo_aom_IMG",
        frequency=219.0 * MHz,
        attenuation=17.5 * dB,
    ),
    SUServoedBeam(
        name="PUMP",
        suservo_device="suservo_aom_PUMP",
        frequency=86.0 * MHz,
        attenuation=19 * dB,
    ),
    SUServoedBeam(
        name="LATX",
        suservo_device="suservo_aom_LATX",
        frequency=200.0 * MHz,
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
        attenuation=19.0 * dB,
    ),
    SUServoedBeam(
        name="CDT2",
        suservo_device="suservo_aom_CDT2",
        frequency=110.0 * MHz,
        attenuation=19.0 * dB,
    ),
]
# Convert to dict for ease of use
SUSERVOED_BEAMS = {beam.name: beam for beam in SUSERVOED_BEAMS}

# map from class to dict for initializing devices
device_arrays.update(
    {
        Eom: EOMS,
        VDrivenSupply: VDRIVEN_SUPPLIES,
        CoilPair: COIL_PAIRS,
        Shutter: SHUTTERS,
        SUServoedBeam: SUSERVOED_BEAMS,
        # Add other classes as needed
    }
)
