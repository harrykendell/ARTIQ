from artiq.language.units import A, MHz, V, dB, ms
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
        max_output=1.0 * A,
        default_output=0.0 * A,
    ),
    VDrivenSupply(
        name="X2",
        fastino="fastino",
        ch=1,
        gain=2.0 * A / V,
        max_output=2.5 * A,
        default_output=1.0 * A,
    ),
    VDrivenSupply(
        name="Y",
        fastino="fastino",
        ch=2,
        gain=0.5 * A / V,
        max_output=1.0 * A,
        default_output=0.0 * A,
    ),
    VDrivenSupply(
        name="Z",
        fastino="fastino",
        ch=3,
        gain=2.0 * A / V,
        max_output=0.85 * A,
        default_output=0.0 * A,
    ),
    VDrivenSupply(
        name="push_780",
        fastino="fastino",
        ch=4,
        gain=222 * MHz / V,
        min_output=-200
        * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V (7.5V is damage)
        max_output=200
        * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V (7.5V is damage)
        default_output=0.0 * MHz,
        unit="MHz",
    ),
    VDrivenSupply(
        name="push_852",
        fastino="fastino",
        ch=5,
        gain=83 * MHz / V,
        min_output=-300
        * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V (7.5V is damage)
        max_output=300
        * MHz,  # we are in 150Ω mode so max JP5 open -> +-5V (7.5V is damage)
        default_output=0.0 * MHz,
        unit="MHz",
    ),
]
# Convert to dict for ease of use
VDRIVEN_SUPPLIES = {supply.name: supply for supply in VDRIVEN_SUPPLIES}

THORLABS_SHUTTER_DELAY = 35.0 * ms
EBAY_SHUTTER_DELAY = 25.0 * ms
# the switch on time is actually quick fast. The limit is the dislike of short pulses

SHUTTERS = [
    Shutter(name="2DMOT", ttl="shutter_2DMOT", delay=THORLABS_SHUTTER_DELAY),
    Shutter(name="3DMOT", ttl="shutter_3DMOT", delay=THORLABS_SHUTTER_DELAY),
    Shutter(name="IMG", ttl="shutter_IMG", delay=EBAY_SHUTTER_DELAY),
    Shutter(name="LATTICE", ttl="shutter_LATTICE", delay=THORLABS_SHUTTER_DELAY),
]
SHUTTERS = {shutter.name: shutter for shutter in SHUTTERS}

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
        frequency=190.5 * MHz,
        attenuation=17.0 * dB,
        shutter_device="shutter_3DMOT,shutter_2DMOT",
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
        attenuation=18.0 * dB,
        # shutter_device="shutter_IMG",
        # shutter_delay=EBAY_SHUTTER_DELAY,
        setpoint=0.2 * V,
        # servo_enabled=True,
        # calib_gain=36.64e-3,
        # calib_offset=-0.87e-3,
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
        calib_gain=2415.00,
        calib_offset=0.0,
        setpoint=3.0 * V,  # 0.324 * V,
    ),
    SUServoedBeam(
        name="CDT2",
        suservo_device="suservo_aom_CDT2",
        frequency=110.0 * MHz,
        attenuation=18.0 * dB,
        servo_enabled=True,
        photodiode_offset=0.00 * V,
        calib_gain=1046.0,
        calib_offset=-196.8,
        setpoint=0.0 * V,
    ),
]
# Convert to dict for ease of use
SUSERVOED_BEAMS = {beam.name: beam for beam in SUSERVOED_BEAMS}

# map from class to dict for initializing devices
device_arrays.update({
    Eom: EOMS,
    Shutter: SHUTTERS,
    VDrivenSupply: VDRIVEN_SUPPLIES,
    SUServoedBeam: SUSERVOED_BEAMS,
    # Add other classes as needed
})
