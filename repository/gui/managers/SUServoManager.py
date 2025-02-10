from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay, TInt64

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel, COEFF_WIDTH
from artiq.coredevice.ttl import TTLInOut

import numpy as np
import logging


class SUServoManager:  # {{{
    """
    Manages a single SUServo device with 8 channels

    It tries to load the state from the dataset provided, if it doesn't exist it will create a new one
    """

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        suservo: SUServo,
        suservo_chs: list[SUServoChannel],
        shutters: list[TTLInOut],
        name="suservo",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.suservo: SUServo = suservo
        self.channels: list[SUServoChannel] = suservo_chs
        self.shutters: list[TTLInOut] = shutters
        self.name = name

        assert len(self.channels) == 8, "There must be 8 channels per SUServo"

        datasets = [
            "enabled",
            "gains",
            "atts",
            "freqs",
            "en_outs",
            "ys",
            "en_iirs",
            "offsets",
            "Ps",
            "Is",
            "Gls",
            "en_shutters",
        ]
        defaults = [
            1,
            [0] * 8,
            [16.5] * 8,
            [204e6, 193e6, 219e6, 86e6, 200e6, 200e6, 110e6, 110e6],
            [0] * 8,
            [1.0] * 8,
            [0] * 8,
            [-0.1] * 8,
            [-30.] * 8,
            [-200000.0] * 8,
            [-200.0] * 8,
            [0] * 2,
        ]
        units = [
            None,
            "dB",
            "dB",
            "MHz",
        ] + [None] * 8
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
    def get_adc(self, ch):
        """
        Get the ADC value for a given channel
        Delays by 20us to ensure the servo was disabled
        """
        self.suservo.set_config(0)
        delay(10 * us)
        v = self.suservo.get_adc(ch)
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
    def enable(self, ch: np.int32):
        """Enable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 1)
        self.core.break_realtime()
        self.channels[ch].set(1, self.en_iirs[ch], ch)

    @kernel
    def disable(self, ch: np.int32):
        """Disable a given channel"""
        self._mutate_and_set_int("en_outs", self.en_outs, ch, 0)
        self.core.break_realtime()
        self.channels[ch].set(0, self.en_iirs[ch], ch)

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
    def set_dds(self, ch: np.int32, freq, offset):
        self._mutate_and_set_float("freqs", self.freqs, ch, freq)
        offset = -offset * (10.0 ** (self.gains[ch] - 1))
        self._mutate_and_set_float("offsets", self.offsets, ch, offset)

        self.core.break_realtime()

        self.channels[ch].set_dds(profile=ch, frequency=freq * MHz, offset=offset)

    @kernel
    def set_freq(self, ch: np.int32, freq):
        self._mutate_and_set_float("freqs", self.freqs, ch, freq * MHz)
        # 0 MHz <= f <= 400 MHz
        if freq < 0:
            raise ValueError("Frequency too low")
        if freq > 400.0:
            raise ValueError("Frequency too high")
        self.core.break_realtime()

        self.channels[ch].set_dds(
            profile=ch, frequency=freq * MHz, offset=self.offsets[ch]
        )

    @kernel
    def set_offset(self, ch: np.int32, v):
        self.set_dds(ch, self.freqs[ch], v)

    @kernel
    def set_y(self, ch: np.int32, y):
        self._mutate_and_set_float("ys", self.ys, ch, y)

        self.core.break_realtime()
        self.channels[ch].set_y(profile=ch, y=y)

    @kernel
    def set_iir(self, ch: np.int32, adc, P, I, Gl):
        self._mutate_and_set_float("Ps", self.Ps, ch, P)
        self._mutate_and_set_float("Is", self.Is, ch, I)
        self._mutate_and_set_float("Gls", self.Gls, ch, Gl)

        logging.warning("Setting IIR for channel %d: P=%f, I=%f, Gl=%f", ch, P, I, Gl)
        self.core.break_realtime()
        self.channels[ch].set_iir(profile=ch, adc=adc, kp=P, ki=I, g=Gl)

    @kernel
    def enable_iir(self, ch: np.int32):
        self._mutate_and_set_int("en_iirs", self.en_iirs, ch, 1)

        self.core.break_realtime()
        self.channels[ch].set(self.en_outs[ch], 1, ch)

    @kernel
    def disable_iir(self, ch: np.int32):
        self._mutate_and_set_int("en_iirs", self.en_iirs, ch, 0)

        self.core.break_realtime()
        self.channels[ch].set(self.en_outs[ch], 0, ch)

    @kernel
    def open_shutter(self, ch):
        """Enable a given shutter"""
        self._mutate_and_set_int("en_shutters", self.en_shutters, ch, 1)
        self.core.break_realtime()
        self.shutters[ch].on()

    @kernel
    def close_shutter(self, ch):
        """Disable a given shutter"""
        self._mutate_and_set_int("en_shutters", self.en_shutters, ch, 0)
        self.core.break_realtime()
        self.shutters[ch].off()

    @kernel
    def set_all(self):
        """
        Ensures the SUServo is set to the current state of the manager
        Where possible we extract state from the SUServo and update the dataset
        """

        # Prepare core
        # self.core.reset()
        self.core.break_realtime()
        self.suservo.set_config(enable=0)
        delay(50 * ms)
        self.suservo.init()
        delay(150 * ms)

        # shutters
        for shutter in range(len(self.shutters)):
            if self.en_shutters[shutter]:
                self.open_shutter(shutter)
            else:
                self.close_shutter(shutter)

        delay(10 * ms)
        self.experiment.set_dataset(
            self.name + ".enabled", self.enabled, persist=True, archive=False
        )
        self.core.break_realtime()
        # Initialize SUServo - this will leave it disabled
        self.suservo.init()
        self.core.break_realtime()
        delay(500 * ms)

        # buffer = [0] * 8
        for ch in range(8):
            # self.core.break_realtime()
            # self.channels[ch].get_profile_mu(ch, buffer)
            # delay(150 * ms)
            # if there doesn't seem to be any state held in the suservo channel we just use our dataset values
            # if (
            #     self.suservo.ddses[0].ftw_to_frequency(buffer[0] << 16 | buffer[6])
            #     != 0.0
            # ):
            #     delay(50 * ms)
            #     logging.info(
            #         "Loading state from SUServo Ch%d\nfreq %.1f MHz targetting %sV giving y=%f",
            #         ch,
            #         self.suservo.ddses[0].ftw_to_frequency(buffer[0] << 16 | buffer[6])
            #         / MHz,
            #         buffer[4] / (1 << COEFF_WIDTH - 1),
            #         self.channels[ch].get_y(ch),
            #     )
            #     self.core.break_realtime()
            #     delay(100 * us)
            #     self._mutate_and_set_float(
            #         "offsets", self.offsets, ch, buffer[4] / (1 << COEFF_WIDTH - 1)
            #     )
            #     self._mutate_and_set_float(
            #         "freqs",
            #         self.freqs,
            #         ch,
            #         self.suservo.ddses[0].ftw_to_frequency(buffer[0] << 16 | buffer[6]),
            #     )
            #     self._mutate_and_set_float(
            #         "ys", self.ys, ch, self.channels[ch].get_y(ch)
            #     )

            self.core.break_realtime()
            # set gain on Sampler channel  to 10^gain - these are wiped in the init
            self.suservo.set_pgia_mu(ch, self.gains[ch])

            # Set profile parameters
            self.set_dds(ch, self.freqs[ch], self.offsets[ch])

            delay(200 * us)
            # PI loop params
            self.channels[ch].set_iir(
                profile=ch,
                adc=ch,
                kp=self.Ps[ch],
                ki=self.Is[ch],
                g=self.Gls[ch],
            )
            delay(20 * us)
            self.channels[ch].set_y(profile=ch, y=self.ys[ch])

        for ch in range(8):
            # set attenuation on all 4 channels - we set all from the dataset then overwrite the one we want
            self.suservo.cplds[ch // 4].set_att(ch % 4, self.atts[ch])
            self.channels[ch].set(
                en_out=self.en_outs[ch], en_iir=self.en_iirs[ch], profile=ch
            )
            delay(5 * 1.2 * us)

        self.suservo.set_config(enable=self.enabled)
