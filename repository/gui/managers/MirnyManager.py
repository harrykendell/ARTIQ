from artiq.experiment import EnvExperiment, kernel
from artiq.language import MHz, dB

from artiq.coredevice.core import Core, rtio_get_counter, at_mu
from artiq.coredevice.almazny import AlmaznyChannel
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.mirny import Mirny

from numpy import int32


class MirnyManager:  # {{{
    """Manage configured EOMs through semantic scalar datasets."""

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        channels: list[ADF5356],
        almazny: list[AlmaznyChannel],
        eoms,
        eom_channels,
        name="mirny",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.cpld: Mirny = channels[0].cpld
        self.channels: list[ADF5356] = channels
        self.almazny: list[AlmaznyChannel] = almazny
        self.eoms = list(eoms)
        self.eom_channels = list(eom_channels)
        self.name = name

        if not self.eoms:
            raise ValueError("At least one Eom must be configured for Mirny")
        if len(self.channels) != len(self.almazny):
            raise ValueError("Mirny and Almazny physical channels must correspond")
        if len(self.eoms) != len(self.eom_channels):
            raise ValueError("Eom definitions and logical channels must correspond")
        if len(set(self.eom_channels)) != len(self.eom_channels) or any(
            channel < 0 or channel >= len(self.channels)
            for channel in self.eom_channels
        ):
            raise ValueError("Eom logical channels must be unique and in range")
        if len({eom.name for eom in self.eoms}) != len(self.eoms):
            raise ValueError("Eom names must be unique")

        # Unconfigured physical channels have no datasets or semantic identity;
        # they are initialized safely off at maximum attenuation.
        self.en_almazny = [False] * len(self.channels)
        self.atts = [31.5] * len(self.channels)
        self.freqs = [53.125] * len(self.channels)
        self.en_outs = [False] * len(self.channels)
        self.almazny_enabled_datasets = [""] * len(self.channels)
        self.attenuation_datasets = [""] * len(self.channels)
        self.frequency_datasets = [""] * len(self.channels)
        self.output_enabled_datasets = [""] * len(self.channels)

        for eom, channel in zip(self.eoms, self.eom_channels):
            prefix = f"{name}.{eom.name}"
            self.almazny_enabled_datasets[channel] = f"{prefix}.almazny_enabled"
            self.attenuation_datasets[channel] = f"{prefix}.attenuation"
            self.frequency_datasets[channel] = f"{prefix}.frequency"
            self.output_enabled_datasets[channel] = f"{prefix}.output_enabled"

            self.en_almazny[channel] = bool(
                experiment.get_dataset(
                    self.almazny_enabled_datasets[channel],
                    default=eom.almazny_enabled,
                )
            )
            self.atts[channel] = (
                float(
                    experiment.get_dataset(
                        self.attenuation_datasets[channel],
                        default=eom.attenuation,
                    )
                )
                / dB
            )
            self.freqs[channel] = (
                float(
                    experiment.get_dataset(
                        self.frequency_datasets[channel],
                        default=eom.frequency / 2,
                    )
                )
                / MHz
            )
            self.en_outs[channel] = bool(
                experiment.get_dataset(
                    self.output_enabled_datasets[channel],
                    default=eom.mirny_enabled,
                )
            )

            self._persist(
                self.almazny_enabled_datasets[channel], self.en_almazny[channel]
            )
            self._persist(
                self.attenuation_datasets[channel], self.atts[channel] * dB, unit="dB"
            )
            self._persist(
                self.frequency_datasets[channel], self.freqs[channel] * MHz, unit="MHz"
            )
            self._persist(self.output_enabled_datasets[channel], self.en_outs[channel])

        self.set_all()

    def _persist(self, path, value, unit=None):
        self.experiment.set_dataset(
            path,
            value,
            persist=True,
            broadcast=True,
            unit=unit,
        )

    def _configured_path(self, paths, ch):
        path = paths[ch]
        if not path:
            raise ValueError("Mirny channel has no configured semantic Eom")
        return path

    def set_almazny(self, ch: int32, state: int32 = 1):
        self.en_almazny[ch] = bool(state)
        self._persist(
            self._configured_path(self.almazny_enabled_datasets, ch),
            self.en_almazny[ch],
        )
        self._set_almazny_hardware(ch, self.en_almazny[ch])

    @kernel
    def _set_almazny_hardware(self, ch, state):
        self.core.break_realtime()
        self.almazny[ch].set(self.atts[ch] * dB, state, bool(state))

    def enable_almazny(self, ch):
        self.set_almazny(ch, 1)

    def disable_almazny(self, ch):
        self.set_almazny(ch, 0)

    def enable(self, ch):
        """Enable a given channel"""
        self.en_outs[ch] = True
        self._persist(self._configured_path(self.output_enabled_datasets, ch), True)
        self._set_output_enabled_hardware(ch, True)

    def disable(self, ch: int32):
        """Disable a given channel"""
        self.en_outs[ch] = False
        self._persist(self._configured_path(self.output_enabled_datasets, ch), False)
        self._set_output_enabled_hardware(ch, False)

    @kernel
    def _set_output_enabled_hardware(self, ch, enabled):
        self.core.break_realtime()
        if enabled:
            self.channels[ch].sw.on()
        else:
            self.channels[ch].sw.off()

    def set_att(self, ch: int32, att: float):
        self.atts[ch] = float(att)
        self._persist(
            self._configured_path(self.attenuation_datasets, ch),
            self.atts[ch] * dB,
            unit="dB",
        )
        self._set_att_hardware(ch, self.atts[ch], self.en_almazny[ch])

    @kernel
    def _set_att_hardware(self, ch, att, almazny_enabled):
        self.core.break_realtime()
        self.channels[ch].set_att(att * dB)
        self.almazny[ch].set(att * dB, almazny_enabled, bool(almazny_enabled))

    def set_freq(self, ch: int32, freq: float):
        """
        Frequency in MHz
        """
        # 53.125 MHz <= f <= 6800 MHz
        if freq < 53.125:
            raise ValueError("Frequency too low")
        if freq > 6800.0:
            raise ValueError("Frequency too high")
        self.freqs[ch] = float(freq)
        self._persist(
            self._configured_path(self.frequency_datasets, ch),
            self.freqs[ch] * MHz,
            unit="MHz",
        )
        self._set_freq_hardware(ch, self.freqs[ch])

    @kernel
    def _set_freq_hardware(self, ch, freq):
        # self.core.break_realtime() but faster
        at_mu(rtio_get_counter() + 1000)
        self.channels[ch].set_frequency(freq * MHz)

    def set_all(self):
        """Restore configured state and safely disable unconfigured channels."""
        self._set_all_hardware()

    @kernel
    def _set_all_hardware(self):
        # Prepare core
        self.core.break_realtime()

        # Initialize Mirny CPLD - shared by all Mirny channels
        self.cpld.init()

        # Initialize Mirny channels
        for ch in range(len(self.channels)):
            # Initialize Mirny channel ch
            self.channels[ch].init()
            self.channels[ch].set_att(self.atts[ch] * dB)
            at_mu(rtio_get_counter() + 1000)
            self.channels[ch].set_frequency(self.freqs[ch] * MHz)
            if self.en_outs[ch]:
                self.channels[ch].sw.on()
            else:
                self.channels[ch].sw.off()

        # Initialize Almazny
        self.core.break_realtime()
        for ch in range(len(self.channels)):
            state = self.en_almazny[ch]
            self.almazny[ch].set(self.atts[ch] * dB, state, bool(state))
