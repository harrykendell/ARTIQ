from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay, TInt64

from artiq.coredevice.core import Core
from artiq.coredevice.almazny import AlmaznyLegacy
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.mirny import Mirny


class MirnyManager:  # {{{
    """
    Manages a mirny with almazny mezzanine

    Data is loaded from the device params
    """

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        channels: list[ADF5356],
        almazny: AlmaznyLegacy,
        name="mirny",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.cpld: Mirny = channels[0].cpld
        self.channels: list[ADF5356] = channels
        self.almazny: AlmaznyLegacy = almazny
        self.name = name

        print("do init here...")
        self.core.reset()

        # init Mirny CPLD - shared by all Mirny channels
        self.channels[0].cpld.init()

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
        self.mirny.info()

    @kernel
    def get_adc(self, ch):
        """
        Get the ADC value for a given channel
        Delays by 20us to ensure the servo was disabled
        """
        self.suservo.set_config(0)
        delay(10 * us)
        v = self.channels[ch].get_adc(0)
        self.suservo.set_config(self.enabled)
        delay(10 * us)
        return v

    @kernel
    def _mutate_and_set_float(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50 * ms)

    @kernel
    def _mutate_and_set_int(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50 * ms)

    @kernel
    def enable_servo(self):
        self.experiment.set_dataset(
            self.name + ".enabled", 1, persist=True, archive=False
        )
        self.enabled = 1
        self.core.break_realtime()
        self.suservo.set_config(enable=1)

    @kernel
    def disable_servo(self):
        self.experiment.set_dataset(
            self.name + ".enabled", 0, persist=True, archive=False
        )
        self.enabled = 0
        self.core.break_realtime()
        self.suservo.set_config(enable=0)

    @kernel
    def enable(self, ch):
        """Enable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 1)
        self.core.break_realtime()
        self.channels[ch].set(1, self.en_iirs[ch])

    @kernel
    def disable(self, ch):
        """Disable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 0)
        self.core.break_realtime()
        self.channels[ch].set(0, self.en_iirs[ch])

    @kernel
    def set_gain(self, ch, gain):
        self._mutate_and_set_float("gains", self.gains, ch, gain)
        self.core.break_realtime()
        self.suservo.set_pgia_mu(ch, gain)

    @kernel
    def set_att(self, ch, att):
        self._mutate_and_set_float("atts", self.atts, ch, att)

        # We have to write all 4 channels at once - so convert each to mu and accumulate into reg
        reg = 0
        for i in range(4):
            reg += self.suservo.cplds[0].att_to_mu(
                self.atts[i if ch < 4 else 4 + i]
            ) << (i * 8)

        self.core.break_realtime()
        self.suservo.cplds[ch // 4].set_all_att_mu(reg)

    @kernel
    def set_dds(self, ch, freq, offset):
        offset = -offset * (10.0 ** (self.gains[ch] - 1))
        self._mutate_and_set_float("freqs", self.freqs, ch, freq)
        self._mutate_and_set_float("offsets", ch, offset)

        self.core.break_realtime()

        self.channels[ch].set_dds(profile=0, frequency=freq * MHz, offset=offset)

    @kernel
    def set_freq(self, ch, freq):
        self._mutate_and_set_float("freqs", self.freqs, ch, freq * MHz)

        self.core.break_realtime()

        self.channels[ch].set_dds(
            profile=0, frequency=freq * MHz, offset=self.offsets[ch]
        )

    @kernel
    def set_y(self, ch, y):
        self._mutate_and_set_float("ys", self.ys, ch, y)

        if self.en_iirs[ch] == 1:
            print("Cannot set y when IIR is enabled")
        else:
            self.core.break_realtime()
            self.channels[ch].set_y(profile=0, y=y)

    @kernel
    def set_iir(self, ch, adc, P, I, Gl):
        self._mutate_and_set_int("sampler_chs", self.sampler_chs, ch, adc)
        self._mutate_and_set_float("Ps", self.Ps, ch, P)
        self._mutate_and_set_float("Is", self.Is, ch, I)
        self._mutate_and_set_float("Gls", self.Gls, ch, Gl)

        self.core.break_realtime()

        self.channels[ch].set_iir(profile=0, adc=adc, kp=P, ki=I, g=Gl)

    @kernel
    def enable_iir(self, ch):
        self._mutate_and_set_int("en_iirs", self.en_iirs, ch, 1)

        self.core.break_realtime()
        self.channels[ch].set(self.en_outs[ch], 1)

    @kernel
    def disable_iir(self, ch):
        self._mutate_and_set_int("en_iirs", self.en_iirs, ch, 0)

        self.core.break_realtime()
        self.channels[ch].set(self.en_outs[ch], 0)
