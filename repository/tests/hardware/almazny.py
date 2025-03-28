from artiq.experiment import *
from artiq.language import MHz, delay, ms, dB
from artiq.coredevice.adf5356 import ADF5356

from artiq.coredevice.almazny import AlmaznyLegacy
from artiq.coredevice.core import Core


class TestMirny(EnvExperiment):
    """Test Mirny and Almazny.

    We set `frequency` on the Almazny channel 0 and `frequency/2` on the Mirny channel specified by `Channel`.
    """

    def build(self):
        self.setattr_argument("Channel", NumberValue(default=0, precision=0, min=0, max=3, step=1, type="int"), tooltip="Mirny channel.")
        self.setattr_argument("attenuation", NumberValue(default=0.0, unit="dB", precision=1, min=0.0, max=31.5, step=0.5, type="float"), tooltip="Attenuation to set on the Mirny.")
        
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

        self.core: Core = self.get_device("core")
        self.mirny: ADF5356 = self.get_device(f"mirny_ch{self.Channel}")
        self.almazny: AlmaznyLegacy = self.get_device("mirny_almazny")

    @kernel
    def run(self):
        self.core.reset()

        # init Mirny CPLD - shared by all Mirny channels
        self.mirny.cpld.init()

        # init Mirny channel 0
        self.core.break_realtime()
        self.mirny.init()
        self.mirny.set_att(self.attenuation)
        self.mirny.set_frequency(self.frequency / 2.0)
        delay(100 * ms)
        self.core.break_realtime()
        self.mirny.sw.on()
        self.core.break_realtime()

        self.almazny.init()
        self.core.break_realtime()
        self.almazny.output_toggle(True)
        for ch in range(4):
            self.almazny.set_att(ch, self.attenuation, True)
