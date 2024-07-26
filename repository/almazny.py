from artiq.experiment import *
from artiq.language import MHz, delay, ms, dB
from artiq.coredevice.adf5356 import ADF5356

from artiq.coredevice.almazny import AlmaznyChannel,AlmaznyLegacy
from artiq.coredevice.core import Core

class TestMirny(EnvExperiment):
    """Test Mirny and Almazny.

    We set `frequency` on the Almazny channel 0 and `frequency/2` on the Mirny channel 0.
    We also try to set `frequency` on the Mirny channel 1.
    """

    def build(self):
        self.core: Core = self.get_device("core")
        self.mirny: ADF5356 = self.get_device("mirny_ch0")
        self.almazny: AlmaznyLegacy = self.get_device("mirny_almazny")
        # self.almazny: AlmaznyChannel = self.get_device("almazny_ch0")

        self.setattr_argument(
            "frequency",
            NumberValue(
                unit="MHz",
                default=6800.0 * MHz,
                precision=3,
                min=53.125 * MHz,
                max=13600.0 * MHz,
                type="float",
            ),
            tooltip="Frequency to set on the Almazny with frequency/2 on the Mirny.",
        )
        self.frequency_2 = self.frequency / 2.0 if self.frequency else 0.0 * MHz

    @kernel
    def run(self):
        self.core.reset()

        # init Mirny CPLD - shared by all Mirny channels
        self.mirny.cpld.init()

        # init Mirny channel 0
        self.core.break_realtime()
        self.mirny.init()
        self.mirny.set_att(11.5 * dB)
        self.mirny.sw.on()
        self.core.break_realtime()
        self.mirny.set_frequency(self.frequency)
        delay(100 * ms)
        self.core.break_realtime()

        self.almazny.init()
        self.core.break_realtime()
        self.almazny.output_toggle(True)
        for ch in range(4):
            self.almazny.set_att_mu(ch, 63)

        # self.almazny.set(att=0.0*dB, enable=True, led=True)
        # self.almazny.set_mu(self.almazny.to_mu(0.0,True,True))

        # print(self.mirny.info())
