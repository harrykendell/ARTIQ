from artiq.experiment import *
import sys

sys.path.append(
    __file__.split("repository")[0] + "repository"
)  # link to repository root
from utils.surpress_missing_imports import *


class TTL_Pulse_Train(EnvExperiment):
    """select device by variable"""

    # This code runs on the host device
    def build(self):
        self.setattr_device("core")

        # setup a variable which controls which TTL to read
        self.setattr_argument(
            "ttl_number", NumberValue(type="int", precision=0, step=1, min=0, max=15)
        )

        # activate the ttl device we want
        self.setattr_device(f"ttl{self.ttl_number}")

        # this just allows for easy access with self.ttl as we can't construct strings in kernels
        # if we dont do this we have to access the member through the classes __dict__ attribute :(
        self.ttl = self.__dict__[f"ttl{self.ttl_number}"]

    @kernel  # this code runs on the FPGA
    def run(self):

        self.core.reset()  # resets core device
        self.ttl.output()
        print("We are pulsing TTL number", self.ttl_number)

        self.core.break_realtime()

        for _ in range(1_000_000):
            delay(2 * us)
            self.ttl.pulse(2 * us)
