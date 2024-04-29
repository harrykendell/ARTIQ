from artiq.experiment import *  # imports everything from experiment library

# This code outputs a ramp wave on a single channel of the fastino
# The wave ramps from -10v to 10v with a frequency of 1.28kHz


class Fastino_Ramp_Generator(EnvExperiment):
    """fastino: Ramp Generator"""

    def build(self):  # this code runs from the host device

        self.setattr_device("core")
        self.setattr_device("fastino")

    @kernel  # this code runs on the FPGA
    def run(self):
        self.core.reset()
        n_steps = 100
        voltages = [((10) // n_steps) * i for i in range(-n_steps, n_steps)]
        self.core.break_realtime()  # moves timestamp forward to prevent underflow

        self.fastino.init()
        delay(200 * us)  # 200us delay, to prevent underflow

        while (
            True
        ):  # loops until manually broken(from bash terminal, this requires closing terminal)
            for voltage in voltages_mu:  # loops over all voltages in voltages_mu list

                self.fastino.write_dac(0, voltage)
                self.fastino.load()  # loads buffer to DAC channel

                delay(7 * us)  # 7us delay
                # for 1 channel, 800ns delay prevents underflow but for voltage to reach level, 7us delay is needed
