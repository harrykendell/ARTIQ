import logging

from artiq.coredevice.ad9910 import _AD9910_REG_CFR2
from artiq.coredevice.ad9910 import _AD9910_REG_RAMP_LIMIT
from artiq.coredevice.ad9910 import _AD9910_REG_RAMP_RATE
from artiq.coredevice.ad9910 import _AD9910_REG_RAMP_STEP
from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import EnumerationValue
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue
from artiq.experiment import TFloat
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from utils.get_local_devices import get_local_devices

from icl_repo.lib.fragments.ad9910_ramper import AD9910Ramper

logger = logging.getLogger(__name__)


class TestAD9910Ramper(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        ad9910_channels = get_local_devices(self, AD9910)
        if not ad9910_channels:
            raise ValueError("No AD9910 channels found in device_db")
        self.setattr_argument("channel", EnumerationValue(ad9910_channels))

        self.setattr_fragment("ramper", AD9910Ramper, self.channel)
        self.ramper: AD9910Ramper

        self.setattr_argument(
            "f_min", NumberValue(default=10e6, unit="MHz", precision=6)
        )
        self.setattr_argument(
            "f_max", NumberValue(default=20e6, unit="MHz", precision=6)
        )
        self.setattr_argument(
            "df_dt", NumberValue(default=1e6, unit="MHz", precision=6)
        )

        self.setattr_argument(
            "mode", EnumerationValue(["Triangle", "Positive saw", "Negative saw"])
        )

    def host_setup(self):
        super().host_setup()

        modes = {
            "Triangle": 0,
            "Positive saw": 1,
            "Negative saw": 2,
        }

        self.scan_type = modes[self.mode]

    @kernel
    def run_once(self):
        self.core.break_realtime()

        self.ramper.start_ramp(self.df_dt, self.f_min, self.f_max, self.scan_type)


TestAD9910Ramper = make_fragment_scan_exp(TestAD9910Ramper)
