from repository.models import SUServoedBeam, EOM, VDrivenSupply, Shutter
from artiq.language.units import ms, dB, MHz

EOMS = [
    EOM(
        name="repump_eom",
        frequency=3285.0 * MHz,
        attenuation=3.0 * dB,
        mirny_ch="mirny_eom_repump",
        almazny_ch="almazny_eom_repump",
    )
]
# Convert to dict for ease of use
EOMS = {eom.name: eom for eom in EOMS}

VDRIVEN_SUPPLIES = [
    VDrivenSupply(
        name="X1",
        fastino="fastino",
        ch=0,
        gain=2.0,
        current_limit=3.0,
    ),
    VDrivenSupply(
        name="X2",
        fastino="fastino",
        ch=1,
        gain=2.0,
        current_limit=3.0,
    ),
    VDrivenSupply(
        name="Y",
        fastino="fastino",
        ch=2,
        gain=2.0,
        current_limit=3.0,
    ),
    VDrivenSupply(
        name="Z",
        fastino="fastino",
        ch=3,
        gain=2.0,
        current_limit=3.0,
    ),
    VDrivenSupply(
        name="GreenTA",
        fastino="fastino",
        ch=7,
        gain=0.0,
        current_limit=2.0,
        # TODO: Actually set me up
    ),
    VDrivenSupply(
        name="Dispenser",
        fastino="fastino",
        ch=6,
        gain=0.0,
        current_limit=3.0,
        # TODO: Actually set me up
    ),
]
# Convert to dict for ease of use
VDRIVEN_SUPPLIES = {supply.name: supply for supply in VDRIVEN_SUPPLIES}

SHUTTERS = [
    Shutter(
        name="MOT2D",
        ttl="shutter_2DMOT",
        delay=35.0 * ms,
    ),
    Shutter(
        name="MOT3D",
        ttl="shutter_3DMOT",
        delay=35.0 * ms,
    ),
]
# Convert to dict for ease of use
SHUTTERS = {beam.name: beam for beam in SHUTTERS}

SUSERVOED_BEAMS = [
    SUServoedBeam(
        name="Locking",
        frequency=198.0 * MHz,
        attenuation=16.0 * dB,
        suservo_device="suservo_aom_LOCK",
    ),
    SUServoedBeam(
        name="MOT",
        suservo_device="suservo_aom_MOT",
        frequency=198.0 * MHz,
        attenuation=15.5 * dB,
    ),
    SUServoedBeam(
        name="IMG",
        suservo_device="suservo_aom_IMG",
        frequency=219.0 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="PUMP",
        suservo_device="suservo_aom_PUMP",
        frequency=86.0 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="LATX",
        suservo_device="suservo_aom_LATX",
        frequency=200.0 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="LATY",
        suservo_device="suservo_aom_LATY",
        frequency=200.0 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="CDT1",
        suservo_device="suservo_aom_CDT1",
        frequency=110.0 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="CDT2",
        suservo_device="suservo_aom_CDT2",
        frequency=110.0 * MHz,
        attenuation=20.0 * dB,
    ),
]
# Convert to dict for ease of use
SUSERVOED_BEAMS = {beam.name: beam for beam in SUSERVOED_BEAMS}
