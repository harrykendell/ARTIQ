from artiq.experiment import *

# turns output on, off, and then pulses it
# to view the trace from this on a scope, use a single trigger with at least 16ms measured on scope


class TTL_Pulse_All(EnvExperiment):
    """TTL Pulse All"""

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")

        self.ttlOut=[None]*4
        self.ttl=[None]*12
        for i in range(4):
            self.setattr_device(f"ttl{i}")
            self.ttlOut[i]=self.__dict__[f"ttl{i}"]
        for i in range(4,16):
            self.setattr_device(f"ttl{i}")
            self.ttl[i-4]=self.__dict__[f"ttl{i}"]

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        self.core.break_realtime()

        for ttlout in self.ttlOut:
            ttlout.output()
            delay(1 * us)
        for ttl in self.ttl:
            ttl.output()
            delay(1 * us)

        self.core.break_realtime()
        for _ in range(50000):
                i = 0
                for ttlout in self.ttlOut:
                        i += 1
                        for _ in range(i):
                                ttlout.pulse(1*us)
                                delay(1*us)
                        delay(10*us)
                for ttl in self.ttl:
                        i += 1
                        for _ in range(i):
                                ttl.pulse(1*us)
                                delay(1*us)
                        delay(10*us)
