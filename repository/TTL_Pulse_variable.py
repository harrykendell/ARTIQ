from artiq.experiment import *

# turns output on, off, and then pulses it
# to view the trace from this on a scope, use a single trigger with at least 16ms measured on scope


class TTL_Output_On_Off_Pulse(EnvExperiment):
    """TTL Output On, Off, Pulse"""

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
        self.ttl.output()  # sets TTL as an output
        # moves timestamp forward to prevent collision between ttl.output and ttl.on although appears not to be neccessary in this case.
        delay(1 * us)

        # sets TTL output high for 5ms then sets it to low
        self.ttl.pulse(5 * ms)
        delay(1 * ms)

        # leave it high for a second
        self.ttl.on()
        delay(1*s)
        self.ttl.off()
