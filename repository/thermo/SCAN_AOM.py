import logging

from artiq.coredevice.core import Core
from artiq.experiment import kernel
from ndscan.experiment import BoolParam, EnumerationValue, ExpFragment, FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from repository.fragments.suservo_frag import SUServoFrag
from repository.models.devices import SUServoedBeam
from artiq.language import delay, ms, us


class SetSUServoExpFrag(ExpFragment):
    """
    Scan SUServo output frequency

    This ExpFragment just breaks out the functionality of
    :class:`.SUServoFrag`.
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        suservo_channels = list(SUServoedBeam.keys())
        default: SUServoedBeam = SUServoedBeam[suservo_channels[0]]

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
            "SUServoFrag",
            SUServoFrag,
            SUServoedBeam[self.channel].suservo_device,
        )
        self.SUServoFrag: SUServoFrag

        self.setattr_param(
            "start_freq",
            FloatParam,
            description="Start frequency of the SUServo channel",
            default=200.00 * 1e6,
            min=0,
            max=400e6,  # from AD9910 specs
            unit="MHz",
            step=1,
        )
        self.start_freq: FloatParamHandle

        self.setattr_param(
            "end_freq",
            FloatParam,
            description="End frequency of the SUServo channel",
            default=220.00 * 1e6,
            min=0,
            max=400e6,  # from AD9910 specs
            unit="MHz",
            step=1,
        )
        self.end_freq: FloatParamHandle

        self.setattr_param(
            "step",
            FloatParam,
            description="Frequency step size",
            default=1 * 1e6,
            min=1,
            max=100e6,  # from AD9910 specs
            unit="MHz",
        )

        self.setattr_param(
            "step_duration",
            FloatParam,
            description="step duration",
            default=1000 * ms,
            min=5 * us,
            max=1e6 * us,  # from AD9910 specs
            unit="us",
        )

        self.step_duration: FloatParamHandle

        self.step: FloatParamHandle
        self.Range_size: FloatParamHandle

    @kernel
    def run_once(self):
        logging.warning("clobbering attenuations")
        range_size = int(
            (self.end_freq.get() - self.start_freq.get()) / self.step.get()
        )
        self.core.break_realtime()

        self.SUServoFrag.set_attenuation(self.attenuation.get())

        for i in range(range_size):
            self.SUServoFrag.set_suservo(
                self.start_freq.get() + i * self.step.get(),
                self.amplitude.get(),
                self.attenuation.get(),
                self.rf_switch.get(),
                self.setpoint_v.get(),
                self.enable_iir.get(),
            )
            delay(self.step_duration.get())

        # back to start frequency
        self.SUServoFrag.set_suservo(
            self.start_freq.get(),
            self.amplitude.get(),
            self.attenuation.get(),
            self.rf_switch.get(),
            self.setpoint_v.get(),
            self.enable_iir.get(),
        )


scanSUServoExp = make_fragment_scan_exp(SetSUServoExpFrag)
