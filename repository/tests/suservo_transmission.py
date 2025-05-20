from fragments.suservo_frag import SUServoFrag
from models.devices import SUServoedBeam

from artiq.coredevice.core import Core
from artiq.language import delay, kernel, now_mu, parallel
from artiq.language.units import ms, s
from ndscan.experiment import (
    EnumerationValue,
    ExpFragment,
    FloatParam,
    OnlineFit,
    ResultChannel,
    make_fragment_scan_exp,
)
from ndscan.experiment.parameters import FloatParamHandle


class DoublePassTransmissionFrag(ExpFragment):
    """
    AOM Characterisation

    This will check the transmission of an AOM by reading a photodiode signal.
    It pushes the result to a channel so should be run as an NDScan sweep.
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        suservo_channels = list(SUServoedBeam.keys())
        default: SUServoedBeam = SUServoedBeam[suservo_channels[0]]

        # Allow for the sampler to be a different channel to the suservo
        # This means we need less plugging/unplugging
        for which in ["suservo", "sampler"]:
            ch = which + "_channel"
            self.setattr_argument(
                ch,
                EnumerationValue(suservo_channels, default=default.name),
            )
            if self.__dict__[ch] is None:
                self.__dict__[ch] = default.name

            self.setattr_fragment(
                which, SUServoFrag, SUServoedBeam[self.__dict__[ch]].suservo_device
            )
        self.suservo: SUServoFrag
        self.sampler: SUServoFrag

        # reference for the default suservo values
        self.config: SUServoedBeam = SUServoedBeam[self.suservo_channel]

        self.detuning: FloatParamHandle = self.setattr_param(
            "detuning",
            FloatParam,
            description="Detuning of the AOM from nominal",
            default=0.0,
            min=-400e6,  # from AD9910 specs
            max=400e6,  # from AD9910 specs
            unit="MHz",
            step=1,
        )

        self.voltage: ResultChannel = self.setattr_result("voltage")

    @kernel
    def run_once(self):
        self.core.reset()

        self.suservo.set_dds(
            frequency=self.config.frequency+self.detuning.get(),
            profile=self.suservo.suservo_profile,
            offset=self.suservo.setpoint_to_offset(self.config.setpoint),
        )

        # ensure its settled
        delay(10*ms)

        self.voltage.push(self.sampler.read_adc())

    def get_default_analyses(self):
        return [
            OnlineFit(
                "line",
                data={
                    "x": self.detuning.get(),
                    "y": self.voltage,
                },
            ),
        ]


DoublePassTransmission = make_fragment_scan_exp(DoublePassTransmissionFrag)
