from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.fastino import Fastino
from artiq.experiment import EnvExperiment, kernel
from artiq.language.core import delay
from artiq.language.environment import NumberValue
from artiq.language.units import ms


class DMA_fastino(EnvExperiment):
    """
    Attempt to use the fastino with the DMA to ramp.
    """

    def build(self):
        self.setattr_device("core")
        self.core: Core
        self.setattr_device("core_dma")
        self.core_dma: CoreDMA
        self.setattr_device("fastino")
        self.fastino: Fastino

        self.setattr_argument(
            "fastino_channel",
            NumberValue(default=4, precision=0, scale=1, step=1, min=0, max=32),
        )
        self.fastino_channel: int

        self.setattr_argument(
            "start_voltage",
            NumberValue(
                default=-9.9,
                unit="V",
                precision=5,
                step=0.1,
                min=-10.0,
                max=9.999,
            ),
        )
        self.start_voltage: float

        self.setattr_argument(
            "end_voltage",
            NumberValue(
                default=0.0,
                unit="V",
                precision=5,
                min=-10.0,
                max=9.999,
            ),
        )
        self.end_voltage: float

        self.setattr_argument(
            "duration",
            NumberValue(default=1, unit="ms", scale=ms, precision=5),
        )
        self.duration: float

    @kernel
    def record(self, num_steps=100):
        with self.core_dma.record("ramp"):
            # manually tune steps for now - it will probably want something based on self.fastino.t_frame
            # but this is a start
            t_frame = self.core.mu_to_seconds(self.fastino.t_frame)

            time_step = self.duration / num_steps
            if time_step < t_frame:
                time_step = t_frame
                num_steps = max(1, int(self.duration / time_step))

            for i in range(num_steps):
                self.fastino.set_dac(
                    self.fastino_channel,
                    self.start_voltage
                    + (self.end_voltage - self.start_voltage) * i / num_steps,
                )
                delay(time_step)
            self.fastino.set_dac(self.fastino_channel, self.end_voltage)
            delay(t_frame)

    @kernel
    def run(self):
        self.core.reset()
        # init causes a transient spike to -10V so avoid if possible
        if False:
            self.fastino.init()
            self.fastino.set_continuous(0xFFFFFFFF)

        self.record()
        self.core.break_realtime()

        ramp_handle = self.core_dma.get_handle("ramp")
        self.core.break_realtime()
        # good for multiple playback
        # for i in range(100):
        self.core_dma.playback_handle(ramp_handle)
