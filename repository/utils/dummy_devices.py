"""
This module contains dummy versions of various ARTIQ / NDScan objects. These
exist solely for the purpose of working around ARTIQ's inability to infer the
type of an empty list. You can therefore add one of these into your list in
build() if it's empty, and it won't do anything when called.
"""
from artiq.experiment import kernel
from artiq.experiment import TBool
from artiq.experiment import TFloat
from artiq.experiment import TInt32


class DummySUServoFrag:
    @kernel
    def set_suservo(
        self,
        freq: TFloat,
        amplitude: TFloat,
        attenuation: TFloat = 30.0,
        rf_switch_state: TBool = True,
        setpoint_v: TFloat = 0.0,
        enable_iir: TBool = False,
    ):
        pass

    @kernel
    def set_channel_state(self, rf_switch_state=True, enable_iir=True):
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
    @kernel
    def set_setpoint(self, new_setpoint: TFloat):
        return 0.0
