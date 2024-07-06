import logging

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.dma import dma_is_recording
from artiq.experiment import *
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel


class TestDMADetection(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

    @kernel
    def run(self):
        self.core.break_realtime()

        num0 = dma_is_recording()

        with self.core_dma.record("dma1"):
            num1 = dma_is_recording()

        num2 = dma_is_recording()

        logging.info("num0: %s", num0)
        logging.info("num1: %s", num1)
        logging.info("num2: %s", num2)
