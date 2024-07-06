import logging

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import *
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue


class TestDMAReturnValues(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        self.setattr_device("ttl12")
        self.ttl12: TTLInOut

        self.setattr_argument("delay", NumberValue(1e-6, unit="us", precision=3))
        self.delay: float

    @kernel
    def run(self):
        self.core.reset()

        with self.core_dma.record("dma1"):
            for _ in range(50):
                self.ttl12.pulse(self.delay)
                delay(self.delay)

        dma_handle_1a = self.core_dma.get_handle("dma1")

        with self.core_dma.record("dma2"):
            for _ in range(50):
                self.ttl12.pulse(self.delay)
                delay(self.delay)

        dma_handle_2 = self.core_dma.get_handle("dma2")
        dma_handle_1b = self.core_dma.get_handle("dma2")

        logging.info("dma_handle_1a: %s", dma_handle_1a)
        logging.info("dma_handle_1b: %s", dma_handle_1b)
        logging.info("dma_handle_2: %s", dma_handle_2)

        delay(1.0)
        self.core.wait_until_mu(now_mu())

        self.core.break_realtime()

        # execute RTIO operations in the DMA buffer
        # each playback advances the timeline by 50*(100+100) ns
        self.core_dma.playback_handle(dma_handle_1b)

        self.core_dma.playback_handle(dma_handle_2)
