from artiq.experiment import EnvExperiment, kernel
from artiq.language import ms, MHz, dB, delay

from artiq.coredevice.core import Core, rtio_get_counter, at_mu
from artiq.coredevice.almazny import AlmaznyChannel
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.mirny import Mirny

from numpy import int32


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
        almazny: list[AlmaznyChannel],
        name="mirny",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.cpld: Mirny = channels[0].cpld
        self.channels: list[ADF5356] = channels
        self.almazny: list[AlmaznyChannel] = almazny
        self.name = name

        assert len(self.channels) == 4, "There must be 4 channels per Mirny"

        vals = [
            ("en_almazny", [1] + [0] * 3, None),
            ("atts", [17.0] + [31.5] * 3, "dB"),
            ("freqs", [3285.0] + [4000.0] * 3, "MHz"),
            ("en_outs", [0] * 4, None),
        ]

        for dataset, default, unit in vals:
            temp = experiment.get_dataset(name + "." + dataset, default=default)
            # we set the values back so we are allowed to mutate then later
            experiment.set_dataset(
                name + "." + dataset,
                temp,
                persist=True,
                unit=unit,
            )
            self.__dict__[dataset] = temp

        self.set_all()

    @kernel
    def _mutate_and_set_float(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as
        __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50 * ms)

    @kernel
    def _mutate_and_set_int(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as
        __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50 * ms)

    @kernel
    def set_almazny(self, ch: int32, state: int32 = 1):
        self.experiment.mutate_dataset(self.name + ".en_almazny", ch, state)
        self.en_almazny[ch] = state
        self.core.break_realtime()
        self.almazny[ch].set(self.atts[ch] * dB, state, bool(state))

    @kernel
    def enable_almazny(self, ch):
        self.set_almazny(ch, 1)

    @kernel
    def disable_almazny(self, ch):
        self.set_almazny(ch, 0)

    @kernel
    def enable(self, ch):
        """Enable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 1)
        self.core.break_realtime()
        self.channels[ch].sw.on()

    @kernel
    def disable(self, ch: int32):
        """Disable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 0)
        self.core.break_realtime()
        self.channels[ch].sw.off()

    @kernel
    def set_att(self, ch: int32, att: float):
        self._mutate_and_set_float("atts", self.atts, ch, att)
        self.core.break_realtime()
        # set Att for Mirny channel ch
        self.channels[ch].set_att(att * dB)
        # set Att for Almazny channel ch
        self.set_almazny(ch, self.en_almazny[ch])

    @kernel
    def set_freq(self, ch: int32, freq: float):
        """
        Frequency in MHz
        """
        self._mutate_and_set_float("freqs", self.freqs, ch, freq)
        # 53.125 MHz <= f <= 6800 MHz
        if freq < 53.125:
            raise ValueError("Frequency too low")
        if freq > 6800.0:
            raise ValueError("Frequency too high")

        # self.core.break_realtime() but faster
        at_mu(rtio_get_counter() + 1000)
        self.channels[ch].set_frequency(freq * MHz)

    @kernel
    def set_all(self):
        """
        Ensures the Mirny/Almazny is set to the current state of the manager
        Where possible we extract state and update the dataset
        """

        # Prepare core
        # self.core.reset()
        self.core.break_realtime()

        # Initialize Mirny CPLD - shared by all Mirny channels
        self.cpld.init()

        # Initialize Mirny channels
        for ch in range(4):
            # Initialize Mirny channel ch
            self.channels[ch].init()

            self.set_att(ch, self.atts[ch])
            self.set_freq(ch, self.freqs[ch])
            if self.en_outs[ch]:
                self.enable(ch)
            else:
                self.disable(ch)

        # Initialize Almazny
        self.core.break_realtime()
        for ch in range(4):
            self.set_almazny(ch, self.en_almazny[ch])
