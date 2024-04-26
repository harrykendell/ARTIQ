from artiq.experiment import *
from time import sleep

# turns output on, off, and then pulses it
# to view the trace from this on a scope, use a single trigger with at least 16ms measured on scope


class TTL_Output_On_Off_Pulse(EnvExperiment):
    """TTL Pulse ttl0"""

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")
        self.setattr_device("ttl0")

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        self.core.break_realtime()
        self.ttl0.output()  # sets TTL as an output

        # moves timestamp forward to prevent collision between ttl.output and ttl.on although appears not to be neccessary in this case.
        delay(1 * us)

        # sets TTL output high for 5ms then sets it to low
        for i in range(1_000_000):
                self.ttl0.pulse(5 * ms)
                delay(5 * ms)

        self.ttl0.off()

