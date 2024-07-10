from artiq.experiment import *
from artiq.language import MHz, delay, ms
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.almazny import AlmaznyChannel

class TestMirny(EnvExperiment):
    '''Test Mirny and Almazny.
    
    We set `frequency` on the Almazny channel 0 and `frequency/2` on the Mirny channel 0.
    We also try to set `frequency` on the Mirny channel 1.
    '''
    def build(self):
        self.core = self.get_device("core")
        self.mirny: ADF5356 = self.get_device("mirny_ch0")
        self.almazny: AlmaznyChannel = self.get_device("almazny_ch0")

        self.base_mirny: ADF5356 = self.get_device("mirny_ch1")

        self.setattr_argument("frequency", NumberValue(unit="MHz", default=6800.0*MHz, precision=3, min=53.125*MHz, max=13600.0*MHz, type="float"),tooltip="Frequency to set on the Almazny with frequency/2 on the Mirny.")

    @kernel
    def run(self):
        self.core.reset()

        # init Mirnys
        self.mirny.cpld.init()
        self.mirny.init()

        delay(10 * ms)
        self.base_mirny.cpld.init()
        self.base_mirny.init()


        # max their output powers
        self.mirny.set_att(0.)
        self.mirny.sw.on()
        self.core.break_realtime()

        self.base_mirny.set_att(0.)
        self.base_mirny.sw.on()
        self.core.break_realtime()


        # set freqs
        self.mirny.set_frequency(self.frequency / 2)
        self.almazny.set(att=0., enable=True, led=True)
        self.base_mirny.set_frequency(self.frequency)

        inspect(self)

@rpc(flags={"async"})
def inspect(self):
        print("mirny_ch0 info: {}".format(self.mirny.info()))
        print("mirny_ch1 info: {}".format(self.base_mirny.info()))
