"""
This module contains dummy versions of various ARTIQ / NDScan objects. These
exist solely for the purpose of working around ARTIQ's inability to infer the
type of an empty list. You can therefore add one of these into your list in
build() if it's empty, and it won't do anything when called.
"""

from artiq.experiment import TBool, TFloat, TInt32, kernel
from repository.models.devices import Eom, SUServoedBeam, VDrivenSupply


class DummySUServoFrag:
    @kernel
    def set_suservo(
        self,
        freq: TFloat,
        amplitude: TFloat,
        attenuation: TFloat = 30.0,
        en_out: TBool = True,
        setpoint_v: TFloat = 0.0,
        enable_iir: TBool = False,
    ):
        pass

    @kernel
    def set_channel_state(self, en_out=True, enable_iir=True):
        pass


class DummyTTL:
    @kernel
    def set_o(self, state: bool):
        pass

    @kernel
    def on(self):
        pass

    @kernel
    def off(self):
        pass


class DummyAD9910:
    def __init__(self) -> None:
        self.sw = DummyTTL()
        self.cpld = DummyCPLD()

    @kernel
    def init(self):
        pass

    @kernel
    def set(self, frequency: TFloat = 0.0, amplitude: TFloat = 1.0) -> TFloat:
        return 0.0

    @kernel
    def set_att(self, att: TFloat):
        pass

    @kernel
    def cfg_sw(self, state: TBool):
        pass


class DummyAD9912:
    def __init__(self) -> None:
        self.sw = DummyTTL()
        self.cpld = DummyCPLD()

    @kernel
    def init(self):
        pass

    @kernel
    def set(self, frequency: TFloat = 0.0) -> TFloat:
        return 0.0

    @kernel
    def set_att(self, att: TFloat):
        pass

    @kernel
    def cfg_sw(self, state: TBool):
        pass


class DummyCPLD:
    @kernel
    def init(self):
        pass

    @kernel
    def get_att_mu(self) -> TInt32:
        return 0


class DummyFloatParameterHandle:
    @kernel
    def get(self):
        return 0.0


class DummySUServoChannel:
    servo_channel = 0

    @kernel
    def set_setpoint(self, new_setpoint: TFloat):
        return 0.0

    @kernel
    def set_dds(self, profile, frequency, offset, phase=0.0):
        pass


class DummyEomFrag:
    @kernel
    def set_att(self, attenuation: TFloat, almazny_on: bool = True):
        pass

    @kernel
    def set_freq(self, frequency: TFloat):
        pass


class DummySetSupplies:
    def set_outputs(self, currents):
        pass


DummySUServoedBeam = SUServoedBeam(
    name="dummy",
    frequency=-1.0,
    attenuation=-1.0,
    suservo_device="dummy",
    shutter_device="None",
    shutter_delay=0,
)

DummyEom = Eom("dummy", -1.0, -1.0, "dummy", "dummy")

DummyVDrivenSupply = VDrivenSupply("dummy", "dummy", -1.0)
