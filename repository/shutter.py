from artiq.experiment import *

from utils.surpress_missing_imports import *
from utils.wait_for_enter import is_enter_pressed


class Shutter(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("shutter")

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        self.shutter.output()

        time_to_poll = self.core.seconds_to_mu(100 * ms)

        print("Press ENTER to cancel.")
        # keep this low to avoid long response times due to backed up FIFOs
        # but long enough to poll for enter on the host otherwise we underflow
        self.core.break_realtime()
        delay_mu(time_to_poll)

        while not is_enter_pressed():
            # fill the FIFOs until we build enough of a buffer
            fill_to = self.core.get_rtio_counter_mu() + time_to_poll
            while now_mu() < fill_to:
                # contribute more events to fill the timeline
                for _ in range(100):
                    delay(50 * ms)
                    self.shutter.pulse(50 * ms)

        self.core.reset()  # resets core device to empty FIFOs - this removes scheduled events
