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


class AllSUServoReadingFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_param(
            "waittime",
            FloatParam,
            description="Time between measurements",
            default=0.1,
            min=0,
            max=1000,
            unit="s",
            step=0.01,
        )
        self.waittime: FloatParamHandle

        self.setattr_argument(
            "turn_on_beams_with_default_settings",
            BooleanValue(True),
        )
        self.turn_on_beams_with_default_settings: bool

        self.setattr_argument(
            "enable_servoing",
            BooleanValue(False),
        )
        self.enable_servoing: bool

        self.setattr_argument(
            "subtract_setpoint",
            BooleanValue(False),
        )
        self.subtract_setpoint: bool

        # %% devices

        self.setattr_device("scheduler")

        from copy import deepcopy

        self.suservo_beam_infos = deepcopy(list(SUSERVOED_BEAMS.values()))

        if not self.enable_servoing:
            for info in self.suservo_beam_infos:
                info.servo_enabled = False

        self.adc_readers: List[ReadSUServoADC] = []
        self.photodiode_results_channels: List[ResultChannel] = []
        self.control_signal_results_channels: List[ResultChannel] = []

        for i, beam_info in enumerate(self.suservo_beam_infos):
            suservo_channel_device: SUServoChannel = self.get_device(
                beam_info.suservo_device
            )

            # Define result channels for each SUServo photodiode value
            if i == 0:
                r = self.setattr_result(
                    beam_info.name,
                )
            else:
                r = self.setattr_result(
                    beam_info.name,
                    display_hints={
                        "priority": -1,
                        "share_pane_with": self.suservo_beam_infos[0].name,
                    },
                )

            self.photodiode_results_channels.append(r)

            # ... and control value
            name = beam_info.name + "_control"
            if i == 0:
                r = self.setattr_result(
                    name,
                    display_hints={
                        "priority": -1,
                    },
                )
            else:
                r = self.setattr_result(
                    name,
                    display_hints={
                        "priority": -1,
                        "share_pane_with": self.suservo_beam_infos[0].name + "_control",
                    },
                )
            self.control_signal_results_channels.append(r)

            # Get SUServo reader fragment
            self.adc_readers.append(
                self.setattr_fragment(
                    f"{beam_info.name}_adc_reader",
                    ReadSUServoADC,
                    suservo_channel_device,
                )
            )

        # Get beam setter fragment for all the beams
        self.setattr_fragment(
            "beam_default_setter",
            make_set_beams_to_default(
                suservo_beam_infos=self.suservo_beam_infos,
                name="BeamsSettings",
            ),
        )
        self.beam_default_setter: SetBeamsToDefaults

        # Manually set the red shutters
        self.setattr_device("shutter_aom_2DMOT")
        self.setattr_device("shutter_aom_3DMOT")

        # %% Kernel params

        self.first_run = True

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()

        self.core.break_realtime()

        if self.first_run:
            delay(10 * ms)
            self.shutter_aom_2DMOT.on()
            self.shutter_aom_2DMOT.on()

            self.first_run = False

        if self.turn_on_beams_with_default_settings:
            self.core.break_realtime()
            delay(1 * ms)
            self.beam_default_setter.turn_on_all(light_enabled=True)

    @kernel
    def run_once(self):
        delay(self.waittime.get())

        voltages = [0.0] * len(self.adc_readers)
        ctrl_signals = [0.0] * len(self.adc_readers)

        for i_beam in range(len(self.adc_readers)):
            self.core.break_realtime()
            voltages[i_beam] = (
                self.adc_readers[i_beam].read_adc()
                - self.suservo_beam_infos[i_beam].photodiode_offset
            )
            self.core.break_realtime()
            ctrl_signals[i_beam] = self.adc_readers[i_beam].read_ctrl_signal()

        self.save_data(voltages, ctrl_signals)

    @rpc(flags={"async"})
    def save_data(self, voltages: TArray(TFloat), ctrl_signals: TArray(TFloat)):
        for i_beam, beam_info in enumerate(self.suservo_beam_infos):
            voltage = voltages[i_beam]
            ctrl_signal = ctrl_signals[i_beam]

            if self.subtract_setpoint:
                self.photodiode_results_channels[i_beam].push(
                    voltage - beam_info.setpoint
                )
            else:
                self.photodiode_results_channels[i_beam].push(voltage)

            self.control_signal_results_channels[i_beam].push(ctrl_signal)


SUServoReading = make_fragment_scan_exp(SingleSUServoReadingFrag)
SUServosReading = make_fragment_scan_exp(AllSUServoReadingFrag)
