from artiq.experiment import *

# This code takes a single read from a TTL and prints the voltage

class TTL_Input_Read(EnvExperiment):
    """TTL Input Read"""

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")

        # setup a variable which contrls which TTL to read
        self.setattr_argument(
            "ttl_number", NumberValue(type="int", ndecimals=0, step=1, min=0, max=15)
        )
        self.setattr_device(f"ttl{self.ttl_number}")
        # this just allows for easy access as self.ttl
        self.ttl = self.__dict__[f"ttl{self.ttl_number}"]

    @kernel  # this code runs on the FPGA
    def run(self):
        self.core.reset()  # resets core device
        self.ttl.input()  # sets TTL as an input

        # moves timestamp forward to prevent underflow
        # this can also be achieved with a fixed delay
        self.core.break_realtime()

        delay(1 * s)
        # reads current value of TTL
        self.ttl.sample_input()

        print(self.ttl.sample_get())
