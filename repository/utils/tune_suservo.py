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

from repository.fragments.suservo import LibSetSUServoStatic
from repository.models.devices import SUSERVOED_BEAMS, SUServoedBeam


class SetSUServoTune(ExpFragment):
    """
    Tune the SUServo IIR

    This ExpFragment just breaks out the functionality of
    :class:`.LibSetSUServoStatic`.
    """

    def build_fragment(self):
        self.setattr_device("core")

        suservo_channels = [
            k for k in SUSERVOED_BEAMS.keys() if SUSERVOED_BEAMS[k].setpoint != 0.0
        ]
        default: SUServoedBeam = SUSERVOED_BEAMS[suservo_channels[0]]
        if not suservo_channels:
            raise ValueError("No suservo channels found in device_db")
        self.setattr_argument(
            "channel",
            EnumerationValue(suservo_channels, default=default.name),
        )

        self.setattr_param(
            "kp",
            FloatParam,
            description="Proportional gain of the IIR filter",
            default=-1.0,
        )

        self.setattr_param(
            "ki",
            FloatParam,
            description="Integral gain of the IIR filter",
            default=0.0,
            min=0,
            max=1,
        )
        self.setattr_param(
            "gain_limit",
            FloatParam,
            description="Gain limit of the IIR filter",
            default=0.0,
        )
        self.setattr_param(
            "setpoint_v",
            FloatParam,
            description="Setpoint to servo to",
            default=default.setpoint,
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
            default=default.servo_enabled,
        )

        self.kp: FloatParamHandle
        self.ki: FloatParamHandle
        self.gain_limit: FloatParamHandle
        self.setpoint_v: FloatParamHandle
        self.rf_switch: BoolParamHandle
        self.enable_iir: BoolParamHandle
        self.pgia_setting: IntParamHandle

        self.setattr_fragment("LibSetSUServoStatic", LibSetSUServoStatic, self.channel)
        self.LibSetSUServoStatic: LibSetSUServoStatic

    @kernel
    def run_once(self):
        self.LibSetSUServoStatic.set_iir_params(
            kp=self.kp.get(), ki=self.ki.get(), gain_limit=self.gain_limit.get()
        )

        self.LibSetSUServoStatic.set_setpoint(new_setpoint=self.setpoint_v.get())

        self.LibSetSUServoStatic.set_channel_state(
            self.rf_switch.get(), self.enable_iir.get()
        )

        if not self.enable_iir.get():
            self.LibSetSUServoStatic.set_y(1.0)


SetSUServoSTuneExp = make_fragment_scan_exp(SetSUServoTune)
