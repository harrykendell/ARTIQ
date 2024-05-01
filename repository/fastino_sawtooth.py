import sys, os
sys.path.append(
    os.path.join(os.path.dirname(__file__), "..")
)  # link to repository root
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

        self.setattr_argument("voltage", NumberValue(ndecimals=2, min=-9.99, max=9.99))

    @kernel  # this code runs on the FPGA
    def run(self):
        self.core.reset()
        self.core.break_realtime()

        self.fastino.init()
        delay(200 * us)
        self.fastino.set_leds(0b00000001)
        delay(100 * us)

        voltages = [i/100. for i in range(-999,1000)]
        # for dac in range(32):
        while not is_enter_pressed():
            for v in voltages:
                self.fastino.set_dac(0, v)
                delay(100 * us)
