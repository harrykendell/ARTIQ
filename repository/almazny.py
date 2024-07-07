from artiq.experiment import *
from artiq.language import MHz, delay, ms
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.almazny import AlmaznyChannel

class TestMirny(EnvExperiment):
    def build(self):
        self.core = self.get_device("core")
        self.mirny: ADF5356 = self.get_device("mirny_ch0")
        self.almazny: AlmaznyChannel = self.get_device("almazny_ch0")

        self.setattr_argument("frequency", NumberValue(unit="MHz", default=2000, ndecimals=0, step=1),tooltip="Frequency to set on the Almazny with frequency/2 on the Mirny.")

    @kernel
    def run(self):
        self.core.reset()

        self.mirny.cpld.init()
        self.mirny.init()

        self.mirny.set_att_mu(0)
        self.mirny.sw.on()
        self.core.break_realtime()

        self.mirny.set_frequency(self.frequency / 2 * MHz)

        self.almazny.output_toggle(True)
        self.almazny.att_to_mu(0)
        self.almazny.set_att(0, 0, True)

        delay(20 * ms)
        print(self.mirny.read_muxout())

    def analyze(self):
        print(self.mirny.info())
