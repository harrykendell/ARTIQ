import logging

import numpy as np
from artiq.coredevice.ad9910 import _AD9910_REG_AUX_DAC
from artiq.coredevice.ad9910 import _AD9910_REG_CFR2
from artiq.coredevice.ad9910 import _AD9910_REG_PROFILE3
from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.core import Core
from artiq.coredevice.urukul import *
from artiq.coredevice.urukul import CFG_RST
from artiq.coredevice.urukul import CPLD
from artiq.experiment import BooleanValue
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue
from artiq.experiment import TInt64

logger = logging.getLogger(__name__)
REG_ADDR = 0x05


class SetUrukulAttenuatorRepeatedly(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.channel: AD9910 = self.get_device(
            "urukul9910_aom_doublepass_689_red_injection"
        )

        self.setattr_argument(
            "n_repeats", NumberValue(default=10, precision=0, step=1, type="int")
        )
        self.n_repeats: int

        self.setattr_argument(
            "att", NumberValue(default=0.0, precision=1, step=0.1, type="float")
        )
        self.att: float

    def prepare(self):
        self.urukul: CPLD = self.channel.cpld

    @kernel
    def urukul_rst(self, dds):
        # type:(CPLD) -> None

        """Pulse MASTER_RESET"""

        dds.cfg_write(dds.cfg_reg | (1 << CFG_RST))
        delay(100e-3)
        dds.cfg_write(dds.cfg_reg & ~(1 << CFG_RST))
        delay(2000e-3)

    @kernel
    def read_freq(self):
        logger.info("Reading from dds...")

        self.core.break_realtime()
        freq, phase, amp = self.channel.get()

        logger.info("freq = %s", freq)
        logger.info("phase = %s", phase)
        logger.info("amp = %s", amp)

    @kernel
    def read_status(self):
        self.core.break_realtime()
        status = self.urukul.sta_read()

        logger.info("Read status register: 0x%X", status)

        logger.info("urukul_sta_rf_sw = %s", urukul_sta_rf_sw(status))
        logger.info("urukul_sta_smp_err = %s", urukul_sta_smp_err(status))
        logger.info("urukul_sta_pll_lock = %s", urukul_sta_pll_lock(status))
        logger.info("urukul_sta_ifc_mode = %s", urukul_sta_ifc_mode(status))
        logger.info("urukul_sta_proto_rev = %s", urukul_sta_proto_rev(status))

    @kernel
    def run(self):
        self.read_freq()
        self.read_status()

        logger.warning("Starting set_att with att = %f...", self.att)

        for _ in range(self.n_repeats):
            self.core.break_realtime()
            self.channel.set_att(self.att)
            delay(1.0)
            self.core.wait_until_mu(now_mu())
            logger.info("Setting")

        logger.warning("Completed")

        self.read_freq()
        self.read_status()
