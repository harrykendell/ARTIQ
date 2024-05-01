from artiq.experiment import *
from utils.surpress_missing_imports import *
from utils.wait_for_enter import is_enter_pressed

# turns output on, off, and then pulses it
# to view the trace from this on a scope, use a single trigger with at least 16ms measured on scope


class TTL_Pulse_Train(EnvExperiment):
    """TTL pulse train - variable port"""

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")

        # setup a variable which controls which TTL to read
        self.setattr_argument(
            "ttl_number", NumberValue(type="int", ndecimals=0, step=1, min=0, max=15)
        )
        self.setattr_device(f"ttl{self.ttl_number}")
        # this just allows for easy access as self.ttl
        self.ttl = self.__dict__[f"ttl{self.ttl_number}"]

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        self.ttl.output()

        # we have to delay to allow is_enter_pressed to check for keys
        # delay(0.25*s)
        print("Press ENTER to cancel.")
        while not is_enter_pressed():
            self.core.break_realtime()
            # do not fill the FIFOs too much to avoid long response times
            t = now_mu() - self.core.seconds_to_mu(0.2)
            while self.core.get_rtio_counter_mu() < t:
                pass
            for _ in range(100_000):
                delay(2 * us)
                self.ttl.pulse(2 * us)
