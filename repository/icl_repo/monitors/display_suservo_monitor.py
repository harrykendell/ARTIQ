import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.suservo import SUServo
from artiq.experiment import BooleanValue
from artiq.experiment import delay
from artiq.experiment import EnumerationValue
from artiq.experiment import kernel
from artiq.experiment import ms
from artiq.experiment import rpc
from artiq.experiment import TArray
from artiq.experiment import TFloat
from artiq.master.worker_db import DummyDevice
from artiq_influx_generic import InfluxController
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatParam
from ndscan.experiment import ResultChannel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle

from icl_repo.lib import constants
from icl_repo.lib.fragments.beams.default_beam_setter import (
    make_set_beams_to_default,
)
from icl_repo.lib.fragments.beams.default_beam_setter import SetBeamsToDefaults
from icl_repo.lib.fragments.read_adc import ReadSUServoADC

logger = logging.getLogger(__name__)


class DisplaySingleSUServoMonitorFrag(ExpFragment):
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

        beam_info_names = list(constants.SUSERVOED_BEAMS.keys())
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
            "disable_servoing",
            BooleanValue(True),
        )
        self.disable_servoing: bool

        # %% devices

        self.beam_info = constants.SUSERVOED_BEAMS[
            self.beam_info_name or beam_info_names[0]
        ]

        if self.disable_servoing:
            self.beam_info.servo_enabled = False

        self.suservo_channel_device: SUServoChannel = self.get_device(
            self.beam_info.suservo_device
        )

        # Define result channels as outputs
        self.setattr_result("voltage")
        self.voltage: ResultChannel

        # Get beam setter fragment
        self.setattr_fragment(
            "beam_default_setter",
            make_set_beams_to_default(
                [self.beam_info],
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

        return super().host_setup()

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

        v = self.adc_reader.read_adc() - self.beam_info.photodiode_offset

        self.voltage.push(v)


class DisplayAllSUServoMonitorsFrag(ExpFragment):
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
            "disable_servoing",
            BooleanValue(True),
        )
        self.disable_servoing: bool

        self.setattr_argument(
            "subtract_setpoint",
            BooleanValue(False),
        )
        self.subtract_setpoint: bool

        # %% devices

        self.setattr_device("influx_logger")
        self.influx_logger: InfluxController

        self.setattr_device("scheduler")

        from copy import deepcopy

        self.beam_infos = deepcopy(list(constants.SUSERVOED_BEAMS.values()))

        if self.disable_servoing:
            for info in self.beam_infos:
                info.servo_enabled = False

        self.adc_readers: List[ReadSUServoADC] = []
        self.photodiode_results_channels: List[ResultChannel] = []
        self.control_signal_results_channels: List[ResultChannel] = []

        for i, beam_info in enumerate(self.beam_infos):
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
                        "share_pane_with": self.beam_infos[0].name,
                    },
                )

            self.photodiode_results_channels.append(r)

            # ... and control value
            name = beam_info.name + "_control"
            if i == 0:
                r = self.setattr_result(
                    name,
                )
            else:
                r = self.setattr_result(
                    name,
                    display_hints={
                        "priority": -1,
                        "share_pane_with": self.beam_infos[0].name + "_control",
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
                self.beam_infos,
                name="BeamsSettings",
            ),
        )
        self.beam_default_setter: SetBeamsToDefaults

        # %% Kernel params

        self.first_run = True

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()

        if self.first_run:
            self.core.break_realtime()
            delay(10 * ms)
            if self.turn_on_beams_with_default_settings:
                self.beam_default_setter.turn_on_all(light_enabled=True)

            self.first_run = False

    @kernel
    def run_once(self):
        delay(self.waittime.get())

        voltages = [0.0] * len(self.adc_readers)
        ctrl_signals = [0.0] * len(self.adc_readers)

        for i_beam in range(len(self.adc_readers)):
            self.core.break_realtime()
            voltages[i_beam] = (
                self.adc_readers[i_beam].read_adc()
                - self.beam_infos[i_beam].photodiode_offset
            )
            self.core.break_realtime()
            ctrl_signals[i_beam] = self.adc_readers[i_beam].read_ctrl_signal()

        self.save_data(voltages, ctrl_signals)

    @rpc(flags={"async"})
    def save_data(self, voltages: TArray(TFloat), ctrl_signals: TArray(TFloat)):
        for i_beam, beam_info in enumerate(self.beam_infos):
            voltage = voltages[i_beam]
            ctrl_signal = ctrl_signals[i_beam]

            if self.subtract_setpoint:
                self.photodiode_results_channels[i_beam].push(
                    voltage - beam_info.setpoint
                )
            else:
                self.photodiode_results_channels[i_beam].push(voltage)

            self.control_signal_results_channels[i_beam].push(ctrl_signal)

            self.influx_logger.write(
                tags={
                    "type": self.__class__.__name__,
                    "beam": beam_info.name,
                    "rid": self.scheduler.rid,
                },
                fields={
                    "setpoint": beam_info.setpoint,
                    "reading": voltage,
                    "ctrl_signal": ctrl_signal,
                },
            )


DisplaySingleSUServoMonitor = make_fragment_scan_exp(DisplaySingleSUServoMonitorFrag)
DisplayAllSUServoMonitors = make_fragment_scan_exp(DisplayAllSUServoMonitorsFrag)
