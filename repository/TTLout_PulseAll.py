from artiq.experiment import *

# turns output on, off, and then pulses it
# to view the trace from this on a scope, use a single trigger with at least 16ms measured on scope


class TTL_Pulse_All(EnvExperiment):
    """TTL Pulse All"""

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")

        for i in range(4,16):
            self.setattr_device(f"ttl{i}")

        self.ttls=[self.__dict__[f"ttl{i}"] for i in range(4,16)]

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        # for ttl in self.ttls:
        #     ttl.output()

        delay(500 * ms)

        # sets TTL output high for 5ms then sets it to low
        for ttl in self.ttls:
                ttl.on()
                delay(1 * us)

        delay(10*s)

        for ttl in self.ttls:
             ttl.off()
             delay(1 * us)
