from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.experiment import kernel
from ndscan.experiment import BoolParam
from ndscan.experiment import EnumerationValue
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatParam
from ndscan.experiment import IntParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import BoolParamHandle
from ndscan.experiment.parameters import FloatParamHandle

from repository.fragments.suservo import LibSetSUServoStatic
from repository.models.devices import SUSERVOED_BEAMS, SUServoedBeam

import logging


class SetSUServoStatic(ExpFragment):
    """
    Set a static SUServo output

    This ExpFragment just breaks out the functionality of
    :class:`.LibSetSUServoStatic`.
    """

    def build_fragment(self):
        self.setattr_device("core")

        suservo_channels = list(SUSERVOED_BEAMS.keys())
        default: SUServoedBeam = SUSERVOED_BEAMS[suservo_channels[0]]

        if not suservo_channels:
            raise ValueError("No suservo channels found in device_db")
        self.setattr_argument(
            "channel",
            EnumerationValue(suservo_channels, default=default.name),
        )
        self.channel: str
        if self.channel is None:
            self.channel = default.name

        self.setattr_param(
            "frequency",
            FloatParam,
            description="Static frequency of the SUServo channel",
            default=default.frequency,
            min=0,
            max=400e6,  # from AD9910 specs
            unit="MHz",
            step=1,
        )

        self.setattr_param(
            "amplitude",
            FloatParam,
            description="Amplitude of AD9910 output, from 0 to 1",
            default=default.initial_amplitude,
            min=0,
            max=1,
        )
        self.setattr_param(
            "attenuation",
            FloatParam,
            description="Attenuation on Urukul's variable attenuator",
            default=default.attenuation,
            unit="dB",
            min=0,
            max=31.5,
        )
        self.setattr_param(
            "setpoint_v",
            FloatParam,
            description="Setpoint",
            default=default.setpoint,
            unit="V",
            min=0,
            max=10.0,
        )

        self.setattr_param(
            "rf_switch",
            BoolParam,
            description="State of the RF switch",
            default=True,
        )
        self.setattr_param(
            "enable_iir",
            BoolParam,
            description="Enable the servo",
            default=default.servo_enabled,
        )

        self.amplitude: FloatParamHandle
        self.frequency: FloatParamHandle
        self.attenuation: FloatParamHandle
        self.setpoint_v: FloatParamHandle
        self.rf_switch: BoolParamHandle
        self.enable_iir: BoolParamHandle

        self.setattr_fragment(
            "LibSetSUServoStatic",
            LibSetSUServoStatic,
            SUSERVOED_BEAMS[self.channel].suservo_device,
        )
        self.LibSetSUServoStatic: LibSetSUServoStatic

    @kernel
    def run_once(self):
        logging.warning("clobbering attenuations")
        self.core.break_realtime()

        self.LibSetSUServoStatic.set_all_attenuations(self.attenuation.get())

        self.LibSetSUServoStatic.set_suservo(
            self.frequency.get(),
            self.amplitude.get(),
            self.attenuation.get(),
            self.rf_switch.get(),
            self.setpoint_v.get(),
            self.enable_iir.get(),
        )


SetSUServoStaticExp = make_fragment_scan_exp(SetSUServoStatic)
