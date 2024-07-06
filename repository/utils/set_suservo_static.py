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
from ndscan.experiment.parameters import IntParamHandle

from suservo import LibSetSUServoStatic
from get_local_devices import get_local_devices


class SetSUServoStatic(ExpFragment):
    """
    Set a static SUServo output

    This ExpFragment just breaks out the functionality of
    :class:`.LibSetSUServoStatic`.
    """

    def build_fragment(self):
        self.setattr_device("core")

        self.setattr_param(
            "frequency",
            FloatParam,
            description="Static frequency of the SUServo channel",
            default=100e6,
            min=0,
            max=400e6,  # from AD9910 specs
            unit="MHz",
            step=1,
        )

        self.setattr_param(
            "amplitude",
            FloatParam,
            description="Amplitude of AD9910 output, from 0 to 1",
            default=1.0,
            min=0,
            max=1,
        )
        self.setattr_param(
            "attenuation",
            FloatParam,
            description="Attenuation on Urukul's variable attenuator",
            default=30,
            unit="dB",
            min=0,
            max=31.5,
        )
        self.setattr_param(
            "setpoint_v",
            FloatParam,
            description="Setpoint",
            default=0.0,
            unit="V",
            min=0,
            max=10.0,
        )

        self.setattr_param(
            "pgia_setting",
            IntParam,
            description="PGA setting (0,1,2,3 == 1x,10x,100x,1000x)",
            default=0,
            min=0,
            max=3,
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
            default=True,
        )

        self.amplitude: FloatParamHandle
        self.frequency: FloatParamHandle
        self.attenuation: FloatParamHandle
        self.setpoint_v: FloatParamHandle
        self.rf_switch: BoolParamHandle
        self.enable_iir: BoolParamHandle
        self.pgia_setting: IntParamHandle

        suservo_channels = get_local_devices(self, SUServoChannel)
        if not suservo_channels:
            raise ValueError("No suservo channels found in device_db")
        self.setattr_argument(
            "channel",
            EnumerationValue(suservo_channels, default=suservo_channels[0]),
        )

        self.setattr_fragment("LibSetSUServoStatic", LibSetSUServoStatic, self.channel)
        self.LibSetSUServoStatic: LibSetSUServoStatic

    @kernel
    def run_once(self):
        self.LibSetSUServoStatic.set_suservo(
            self.frequency.get(),
            self.amplitude.get(),
            self.attenuation.get(),
            self.rf_switch.get(),
            self.setpoint_v.get(),
            self.enable_iir.get(),
        )

        self.LibSetSUServoStatic.set_pgia_gain_mu(self.pgia_setting.get())


SetSUServoStaticExp = make_fragment_scan_exp(SetSUServoStatic)
