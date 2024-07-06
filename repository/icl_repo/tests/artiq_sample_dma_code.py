from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue


class DMAPulses(EnvExperiment):
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
        with self.core_dma.record("pulses"):
            # all RTIO operations now go to the "pulses"
            # DMA buffer, instead of being executed immediately.
            for _ in range(50):
                self.ttl12.pulse(self.delay)
                delay(self.delay)

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
