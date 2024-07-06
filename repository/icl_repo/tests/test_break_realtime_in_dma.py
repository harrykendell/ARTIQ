import logging

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import now_mu
from artiq.experiment import NumberValue


class DMABreakRealtime(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        self.setattr_device("ttl12")
        self.ttl12: TTLInOut

        self.setattr_argument("delay", NumberValue(1e-6, unit="us", precision=3))
        self.delay: float

        self.setattr_argument(
            "num", NumberValue(100000, type="int", precision=0, step=1)
        )
        self.num: int

    @kernel
    def record(self):
        t_timeline_a = now_mu()
        t_real_a = self.core.get_rtio_counter_mu()
        with self.core_dma.record("pulses"):
            t_timeline_b = now_mu()
            t_real_b = self.core.get_rtio_counter_mu()

            self.core.break_realtime()

            t_timeline_c = now_mu()
            t_real_c = self.core.get_rtio_counter_mu()

        logging.info(
            "Timeline values: %d, %d, %d", t_timeline_a, t_timeline_b, t_timeline_c
        )
        logging.info("Real values: %d, %d, %d", t_real_a, t_real_b, t_real_c)

    @kernel
    def run(self):
        self.core.reset()
        self.record()
        # prefetch the address of the DMA buffer
        # for faster playback trigger
        pulses_handle = self.core_dma.get_handle("pulses")

        self.core.break_realtime()
        for _ in range(self.num):
            # execute RTIO operations in the DMA buffer
            # each playback advances the timeline by 50*(100+100) ns
            self.core_dma.playback_handle(pulses_handle)
