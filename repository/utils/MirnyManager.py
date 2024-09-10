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

        assert len(self.channels) == 4, "There must be 8 channels per Mirny"

        datasets = [
            "en_almazny",
            "atts",
            "freqs",
            "en_outs",
        ]
        defaults = [
            True,
            [31.5] * 4,
            [3400e6] * 4,
            [1] * 4,
        ]
        units = [
            None,
            "dB",
            "MHz",
            None,
        ]
        for dataset, default, unit in zip(datasets, defaults, units):
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
    def set_almazny(self, state=True):
        self.experiment.set_dataset(
            self.name + ".almazny", state, persist=True, archive=False
        )
        self.en_almazny = state
        self.core.break_realtime()
        self.almazny.output_toggle(state)

    @kernel
    def enable(self, ch):
        """Enable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 1)
        self.core.break_realtime()
        self.channels[ch].sw.on()

    @kernel
    def disable(self, ch):
        """Disable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 0)
        self.core.break_realtime()
        self.channels[ch].sw.off()

    @kernel
    def set_att(self, ch, att):
        self._mutate_and_set_float("atts", self.atts, ch, att)
        self.core.break_realtime()
        # set Att for Mirny channel ch
        self.channels[ch].set_att(0.0 * dB)
        # set Att for Almazny channel ch
        self.almazny.set_att(ch, att * dB, True)

    @kernel
    def set_freq(self, ch, freq):
        self._mutate_and_set_float("freqs", self.freqs, ch, freq * MHz)
        self.core.break_realtime()

        self.channels[ch].set_frequency(freq*MHz)

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
            self.set_freq(ch, self.freqs[ch]/MHz)
            if self.en_outs[ch]:
                self.enable(ch)
            else:
                self.disable(ch)

        # Initialize Almazny
        self.almazny.init()
        self.core.break_realtime()
        self.set_almazny(self.en_almazny)
        for ch in range(4):
            self.almazny.set_att(ch, self.atts[ch] * dB, True)
