from repository.models import SUServoedBeam, EOM, VDrivenSupply, Shutter
from artiq.language.units import MHz, dB

EOMS = {
    EOM(
        name="repump_eom",
        frequency=3285 * MHz,
        attenuation=3.0 * dB,
        mirny_ch="mirny_eom_repump",
        almazny_ch="almazny_eom_repump",
    )
}

VDRIVEN_SUPPLIES = {
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
}

SHUTTERS = {
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
}

SUSERVOED_BEAMS = {
    SUServoedBeam(
        name="Locking",
        suservo_device="suservo_aom_LOCK",
        frequency=198 * MHz,
        attenuation=16.0 * dB,
    ),
    SUServoedBeam(
        name="MOT",
        suservo_device="suservo_aom_MOT",
        frequency=198 * MHz,
        attenuation=15.5 * dB,
    ),
    SUServoedBeam(
        name="IMG",
        suservo_device="suservo_aom_IMG",
        frequency=219 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="PUMP",
        suservo_device="suservo_aom_PUMP",
        frequency=86 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="LATX",
        suservo_device="suservo_aom_LATX",
        frequency=200 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="LATY",
        suservo_device="suservo_aom_LATY",
        frequency=200 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="CDT1",
        suservo_device="suservo_aom_CDT1",
        frequency=110 * MHz,
        attenuation=20.0 * dB,
    ),
    SUServoedBeam(
        name="CDT2",
        suservo_device="suservo_aom_CDT2",
        frequency=110 * MHz,
        attenuation=20.0 * dB,
    ),
}
