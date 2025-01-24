from repository.models import SUServoedBeam, EOM, VDrivenSupply, Shutter

EOMS = [
    EOM(
        name="repump_eom",
        frequency=3285.0,
        attenuation=3.0,
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
    ),
    VDrivenSupply(
        name="X2",
        fastino="fastino",
        ch=1,
        gain=2.0,
    ),
    VDrivenSupply(
        name="Y",
        fastino="fastino",
        ch=2,
        gain=2.0,
    ),
    VDrivenSupply(
        name="Z",
        fastino="fastino",
        ch=3,
        gain=2.0,
    ),
]
# Convert to dict for ease of use
VDRIVEN_SUPPLIES = {supply.name: supply for supply in VDRIVEN_SUPPLIES}

SHUTTERS = [
    Shutter(
        name="MOT2D",
        ttl="shutter_2DMOT",
        delay=0.0,
    ),
    Shutter(
        name="MOT3D",
        ttl="shutter_3DMOT",
        delay=0.0,
    ),
]
# Convert to dict for ease of use
SHUTTERS = {beam.name: beam for beam in SHUTTERS}

SUSERVOED_BEAMS = [
    SUServoedBeam(
        name="Locking",
        frequency=198.0,
        attenuation=16.0,
        suservo_device="suservo_aom_LOCK",
    ),
    SUServoedBeam(
        name="MOT",
        suservo_device="suservo_aom_MOT",
        frequency=198.0,
        attenuation=15.5,
    ),
    SUServoedBeam(
        name="IMG",
        suservo_device="suservo_aom_IMG",
        frequency=219.0,
        attenuation=20.0,
    ),
    SUServoedBeam(
        name="PUMP",
        suservo_device="suservo_aom_PUMP",
        frequency=86.0,
        attenuation=20.0,
    ),
    SUServoedBeam(
        name="LATX",
        suservo_device="suservo_aom_LATX",
        frequency=200,
        attenuation=20.0,
    ),
    SUServoedBeam(
        name="LATY",
        suservo_device="suservo_aom_LATY",
        frequency=200.0,
        attenuation=20.0,
    ),
    SUServoedBeam(
        name="CDT1",
        suservo_device="suservo_aom_CDT1",
        frequency=110.0,
        attenuation=20.0,
    ),
    SUServoedBeam(
        name="CDT2",
        suservo_device="suservo_aom_CDT2",
        frequency=110.0,
        attenuation=20.0,
    ),
]
# Convert to dict for ease of use
SUSERVOED_BEAMS = {beam.name: beam for beam in SUSERVOED_BEAMS}
