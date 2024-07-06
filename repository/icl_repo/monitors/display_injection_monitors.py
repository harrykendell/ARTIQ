import logging

from artiq.coredevice.core import Core
from artiq.coredevice.sampler import Sampler
from artiq.experiment import delay
from artiq.experiment import kernel
from artiq.experiment import ms
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatParam
from ndscan.experiment import ResultChannel
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle

from device_db_config import get_configuration_from_db


logger = logging.getLogger(__name__)


class DisplayInjectionMonitors(ExpFragment):
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

        monitors = get_configuration_from_db("IJD_monitors")

        sampler_name, _ = monitors["blue_IJD1_controller"]
        self.sampler: Sampler = self.get_device(sampler_name)

        # Not used - I've hacked this a bit...
        # self.sampler_channels = [
        #     monitors["blue_IJD1_controller"],
        #     monitors["blue_IJD2_controller"],
        #     monitors["blue_IJD3_controller"],
        #     monitors["red_IJD1_controller"],
        # ]

        # Define result channels as outputs
        self.setattr_result("blue_1")
        self.setattr_result("blue_2", display_hints={"share_pane_with": "blue_1"})
        self.setattr_result("blue_3", display_hints={"share_pane_with": "blue_1"})
        self.setattr_result("red_1", display_hints={"share_pane_with": "blue_1"})
        self.voltage: ResultChannel

    @kernel
    def device_setup(self) -> None:
        self.device_setup_subfragments()
        self.core.break_realtime()
        delay(1 * ms)
        self.sampler.init()

    @kernel
    def run_once(self):
        samples = [0.0] * 8

        delay(self.waittime.get())

        self.sampler.sample(samples)

        self.blue_1.push(samples[0])
        self.blue_2.push(samples[1])
        self.blue_3.push(samples[2])
        self.red_1.push(samples[3])


DisplayInjectionMonitors = make_fragment_scan_exp(DisplayInjectionMonitors)
