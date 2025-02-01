import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.experiment import (
    BooleanValue,
    EnumerationValue,
    kernel,
    ms,
    rpc,
    TArray,
    TFloat,
)
from ndscan.experiment import ExpFragment, FloatParam, ResultChannel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle
from repository.fragments.default_beam_setter import (
    SetBeamsToDefaults,
    make_set_beams_to_default,
)
from repository.models.devices import SUSERVOED_BEAMS
from repository.fragments.read_adc import ReadSUServoADC

logger = logging.getLogger(__name__)


class SingleSUServoReadingFrag(ExpFragment):
    """
    Plot a single SUServo photodiode reading
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")
        self.setattr_device("scheduler")

        self.setattr_param(
            "waittime",
            FloatParam,
            description="Time between measurements",
            default=0.0,
            min=0.05,
            max=10,
            unit="s",
            step=0.01,
        )
        self.waittime: FloatParamHandle

        beam_info_names = list(SUSERVOED_BEAMS.keys())
        self.setattr_argument(
            "beam_info_name",
            EnumerationValue(
                beam_info_names,
                default=beam_info_names[0],
            ),
        )
        self.beam_info_name: str

        self.setattr_argument(
            "turn_on_beam_with_default_settings",
            BooleanValue(True),
        )
        self.turn_on_beam_with_default_settings: bool

        self.setattr_argument(
            "enable_servoing",
            BooleanValue(False),
        )
        self.enable_servoing: bool

        # %% devices

        self.beam_info = SUSERVOED_BEAMS[self.beam_info_name or beam_info_names[0]]

        if not self.enable_servoing:
            self.beam_info.servo_enabled = False

        self.suservo_channel_device: SUServoChannel = self.get_device(
            self.beam_info.suservo_device
        )

        # Get beam setter fragment
        self.setattr_fragment(
            "beam_default_setter",
            make_set_beams_to_default(
                SUSERVOED_BEAMS,
                name="BeamSettings",
            ),
        )
        self.beam_default_setter: SetBeamsToDefaults

        # Get SUServo reader fragment
        self.setattr_fragment("adc_reader", ReadSUServoADC, self.suservo_channel_device)
        self.adc_reader: ReadSUServoADC

        # %% Kernel params
        self.first_run = True

    def host_setup(self):
        # These are conventions in the AION lab:
        self.sampler_channel_number = self.suservo_channel_device.servo_channel
        self.suservo_profile_number = self.suservo_channel_device.servo_channel

        super().host_setup()
        self.name = f"SUServo{self.beam_info_name}"
        self.set_dataset(
            self.name,
            [],
            broadcast=True,
        )

        self.ccb.issue(
            "create_applet",
            self.name,
            f"${{artiq_applet}}plot_xy {self.name}",
        )

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()

        if self.first_run:
            self.core.break_realtime()
            delay(10 * ms)
            if self.turn_on_beam_with_default_settings:
                self.beam_default_setter.turn_on_all(light_enabled=True)

            self.first_run = False

    @kernel
    def run_once(self):
        delay(self.waittime.get())

        self.core.break_realtime()
        while True:
            for i in range(1000):
                v = self.adc_reader.read_adc() - self.beam_info.photodiode_offset
                delay(self.waittime.get())
                self.update_data(v)
            self.reset_data()

    @rpc
    def update_data(self, data):
        self.name = f"SUServo{self.beam_info_name}"
        self.append_to_dataset(self.name, data)

    @rpc
    def reset_data(self):
        self.set_dataset(self.name, [], broadcast=True)


SUServoReading = make_fragment_scan_exp(SingleSUServoReadingFrag)
