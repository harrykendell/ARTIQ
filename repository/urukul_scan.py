from artiq.experiment import *
from artiq.coredevice.ad9910 import PHASE_MODE_ABSOLUTE
import artiq.coredevice.suservo
from artiq.language import MHz, ms, s, delay
import time
import numpy as np


class SingleChannelScan(EnvExperiment):
    """Single channel frecuency sweep"""

    def build(self):
        self.setattr_device("core")
        self.setattr_argument("channel", EnumerationValue(["0", "1", "2", "3"], "0"))
        self.setattr_argument(f"amp", NumberValue(1.0, min=0.0, max=1.0))
        self.setattr_argument(
            "freqs",
            Scannable(
                default=CenterScan(200 * MHz, 20 * MHz, 1 * MHz),
                unit="MHz",
                scale=MHz,
                global_min=1 * MHz,
                global_max=400 * MHz,
            ),
        )

        # client control broadcast: lo traigo para podes darle update a los applets
        self.setattr_device("ccb")

    def run(self):
        self.salida = self.get_device(f"urukul0_ch{self.channel}")
        # Armo dataset exclusivamente con el proposito de mostrar
        # la frecuencia actual en un applet que se actualice
        self.set_dataset(
            "current_freq",
            np.array([self.freqs.sequence[0]]),
            broadcast=True,
            archive=False,
        )
        self.ccb.issue(
            "create_applet",
            "output_frecuency",
            "${artiq_applet}big_number " "current_freq",
        )
        print("Arranco")
        print(f"Canal: {self.channel}")
        print(f"Amp  : {self.amp}\n")

        self.run_kernel()

    @kernel
    def run_kernel(self):
        self.core.reset()
        self.salida.cpld.init()
        self.salida.init()

        delay(10 * ms)

        self.salida.set_amplitude(self.amp)
        self.salida.set_phase_mode(PHASE_MODE_ABSOLUTE)
        self.salida.set(self.freqs.sequence[0])

        for freq in self.freqs.sequence:
            self.salida.sw.pulse(6 * ms)
            self.salida.set(freq)
            self.mutate_dataset("current_freq", 0, freq)
            delay(4 * s)
