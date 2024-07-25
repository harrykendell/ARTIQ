from artiq.experiment import *

from utils.surpress_missing_imports import *
from utils.wait_for_enter import is_enter_pressed

# This code outputs a ramp wave on a single channel of the fastino
# The wave ramps from -10v to 10v with a frequency of 1.28kHz


class Fastino_Ramp_Generator(EnvExperiment):
    """fastino: Ramp Generator"""

    def build(self):
        self.setattr_device("core")
        self.setattr_device("fastino")

        self.setattr_argument(
            "voltage",
            NumberValue(precision=2, min=-9.99, max=9.99, default=10, type="float"),
        )

        num = 1000
        self.v = [10.0 * i / num for i in range(-num, num)]
        self.v += self.v[::-1]

    @kernel  # this code runs on the FPGA
    def run(self):
        self.core.reset()

        self.fastino.init()
        delay(200 * us)
        self.fastino.set_leds(0b01010101)
        delay(100 * us)

        print("Press ENTER to cancel.")
        # keep this low to avoid long response times due to backed up FIFOs
        # but long enough to poll for enter on the host otherwise we underflow
        time_to_poll = self.core.seconds_to_mu(200 * ms)
        gap = self.core.seconds_to_mu(0.1 * ms)
        self.core.break_realtime()
        delay_mu(time_to_poll)

        while not is_enter_pressed():
            # fill the FIFOs until we build enough of a buffer
            fill_to = self.core.get_rtio_counter_mu() + time_to_poll
            while now_mu() < fill_to:
                # contribute more events to fill the timeline
                for _ in range(10):
                    for v in self.v:
                        self.fastino.set_dac(0, v)
                        delay_mu(gap)

        self.fastino.set_leds(0b00000000)
        delay(100 * us)
        self.fastino.set_dac(0, 0.0)
        delay_mu(gap)
