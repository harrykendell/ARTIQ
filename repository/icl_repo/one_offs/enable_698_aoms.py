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
from utils.suservo import LibSetSUServoStatic
from utils.get_local_devices import get_local_devices


class TurnOn698Temporary(ExpFragment):
    """
    Turn on 698 AOMs
    """

    def build_fragment(self):
        self.setattr_device("core")

        self.setattr_param(
            "input_attenuation",
            FloatParam,
            description="Attenuation on Urukul's variable attenuator",
            default=30,
            unit="dB",
            min=0,
            max=31.5,
        )

        self.setattr_param(
            "input_rf_switch",
            BoolParam,
            description="State of the RF switch",
            default=True,
        )

        self.setattr_param(
            "transmission_attenuation",
            FloatParam,
            description="Attenuation on Urukul's variable attenuator",
            default=30,
            unit="dB",
            min=0,
            max=31.5,
        )

        self.setattr_param(
            "transmission_rf_switch",
            BoolParam,
            description="State of the RF switch",
            default=True,
        )

        self.input_attenuation: FloatParamHandle
        self.input_rf_switch: BoolParamHandle
        self.transmission_attenuation: FloatParamHandle
        self.transmission_rf_switch: BoolParamHandle

        self.setattr_fragment(
            "input_aom", LibSetSUServoStatic, "suservo_aom_698_squeezing_cavity_input"
        )
        self.setattr_fragment(
            "transmission_aom",
            LibSetSUServoStatic,
            "suservo_aom_698_squeezing_cavity_transmission",
        )
        self.input_aom: LibSetSUServoStatic
        self.transmission_aom: LibSetSUServoStatic

    @kernel
    def run_once(self):
        self.input_aom.set_suservo(
            80e6,
            1.0,
            self.input_attenuation.get(),
            self.input_rf_switch.get(),
        )
        self.transmission_aom.set_suservo(
            80e6,
            1.0,
            self.transmission_attenuation.get(),
            self.transmission_rf_switch.get(),
        )


SetSUServoStaticExp = make_fragment_scan_exp(TurnOn698Temporary)
