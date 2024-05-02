from artiq.experiment import *
import sys

sys.path.append(
    __file__.split("repository")[0] + "repository"
)  # link to repository root

from utils.surpress_missing_imports import *
from utils.wait_for_enter import is_enter_pressed


class TTL_Pulse_Train(EnvExperiment):
    """continue until enter is pressed"""
    # There are two ways this can cause RTIO underflows
    # 1. The remote call to is_enter_pressed can take longer than the time_to_buffer
    # 2. Filling the timeline takes longer than those events occuring
    #    - This can be mitigated for short sequences by starting with more slack

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")
        self.setattr_device("ttl0")

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        self.ttl0.output()

        print("Press ENTER to cancel.")
        # keep this low to avoid long response times due to backed up FIFOs
        # but long enough to poll for enter on the host otherwise we underflow
        time_to_poll = self.core.seconds_to_mu(100 * ms)
        self.core.break_realtime()
        delay_mu(time_to_poll)

        while not is_enter_pressed():
            # fill the FIFOs until we build enough of a buffer
            fill_to = self.core.get_rtio_counter_mu() + time_to_poll
            while now_mu() < fill_to:
                # contribute more events to fill the timeline
                for _ in range(1_000):
                    delay(200 * us)
                    self.ttl0.pulse(200 * us)
