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
from artiq.experiment import TInt64

logger = logging.getLogger(__name__)
REG_ADDR = 0x05


class ProbeUrukulStatusRegisterAndPLL(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.channel: AD9910 = self.get_device(
            "urukul9910_aom_doublepass_689_red_injection"
        )

        self.setattr_argument("leave_reset", BooleanValue(default=False))
        self.leave_reset: bool

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

        logger.warning("Resetting dds...")

        self.core.break_realtime()
        self.urukul_rst(self.urukul)

        self.read_freq()
        self.read_status()

        logger.warning("Attempting init...")

        self.core.break_realtime()
        self.channel.init()

        self.read_freq()
        self.read_status()

        logger.info("Setting freq = 340e6...")

        self.core.break_realtime()
        self.channel.set(340e6)

        self.read_freq()
        self.read_status()

        if self.leave_reset:
            logger.warning("Resetting dds again...")

            self.core.break_realtime()
            self.urukul_rst(self.urukul)
