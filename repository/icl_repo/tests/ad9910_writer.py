import logging

from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import EnumerationValue
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue
from utils.get_local_devices import get_local_devices

logger = logging.getLogger(__name__)


class AD9910Writer(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        ad9910_devices = get_local_devices(self, AD9910)

        self.setattr_argument("dds_name", EnumerationValue(ad9910_devices))

        self.dds: AD9910 = self.get_device(self.dds_name)

        self.setattr_argument("freq", NumberValue(default=10e6, unit="MHz"))
        self.setattr_argument(
            "amp", NumberValue(default=1, max=1.0, min=0.0, precision=2)
        )
        self.setattr_argument("att", NumberValue(default=30.0, unit="dB"))

    @kernel
    def run(self):
        self.core.reset()
        self.dds.init(blind=False)

        logger.warning(
            "Setting attenuator to %.1f dB - this will affect all four channels",
            self.att,
        )

        logger.info(
            "%s - setting f=%.6f, att = %.1f dB, amp = %.2f",
            self.dds_name,
            self.freq,
            self.att,
            self.amp,
        )

        self.core.break_realtime()
        delay(10e-3)

        self.dds.set(self.freq)
        self.dds.set_amplitude(self.amp)
        self.dds.set_att(self.att)
        self.dds.sw.on()
