from artiq.language import kernel, EnvExperiment, us, ms, MHz, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel
from artiq.coredevice.ttl import TTLInOut

import numpy as np


class SUServoManager:  # {{{
    """
    Manages a single SUServo device with 8 channels

    It tries to load the state from the dataset provided
    if it doesn't exist it will create a new one
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

        vals = [
            ("enabled", 1, None),
            ("gains", [0] * 8, None),
            ("atts", [16.5] * 8, "dB"),
            ("freqs", [198.0, 193.0, 219.0, 86.0, 200.0, 200.0, 110.0, 110.0], "MHz"),
            ("en_outs", [0] * 8, None),
            ("ys", [1.0] * 8, None),
            ("en_iirs", [0] * 8, None),
            ("offsets", [2.5] * 8, "V"),
            ("Ps", [-1.0] * 8, None),
            ("Is", [-200000.0] * 8, None),
            ("Gls", [-200.0] * 8, None),
            ("en_shutters", [0] * 4, None),
            ("calib_gains", [1.0] * 8, None),
            ("calib_offsets", [0.0] * 8, "V"),
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
    def get_adc(self, ch):
        """
        Get the ADC value for a given channel
        Delays by 20us to ensure the servo was disabled
        """
        self.core.break_realtime()
        # self.suservo.set_config(0)
        # delay(50 * us)
        v = self.suservo.get_adc(ch)
        delay(50 * us)
        # self.suservo.set_config(self.enabled)
        # delay(50 * us)
        return v

    @kernel
    def get_y(self, ch: np.int64):
        """
        Get the Y value for a given channel
        Delays by 20us to ensure the servo was disabled
        """
        self.core.break_realtime()
        # self.suservo.set_config(0)
        # delay(50 * us)
        y = self.channels[ch].get_y(ch)
        delay(50 * us)
        # self.suservo.set_config(self.enabled)
        # delay(50 * us)
        return y

    @kernel
    def _mutate_and_set_float(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable
        as __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50 * ms)

    @kernel
    def _mutate_and_set_int(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable
        as __dict__ access is illegal on kernel
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

        # We have to write all 4 channels at once -
        # so convert each to mu and accumulate into reg
        reg = 0
        for i in range(4):
            reg += self.suservo.cplds[0].att_to_mu(
                self.atts[i if ch < 4 else 4 + i]
            ) << (i * 8)

        self.core.break_realtime()
        self.suservo.cplds[ch // 4].set_all_att_mu(reg)

    @kernel
    def offset_to_mu(self, setpoint, ch=0):
        """
        Convert a setpoint in V to the corresponding mu value
        """
        return -setpoint * (10.0 ** (self.gains[ch] - 1))

    @kernel
    def set_dds(self, ch: np.int32, freq, offset):
        """
        Frequency is in MHz
        Offset in V
        """
        if freq < 0.0 or freq > 400.0:
            raise ValueError("Frequency out of range")
        self._mutate_and_set_float("freqs", self.freqs, ch, freq)
        self._mutate_and_set_float("offsets", self.offsets, ch, offset)

        self.core.break_realtime()

        self.channels[ch].set_dds(
            profile=ch,
            frequency=freq * MHz,
            offset=self.offset_to_mu(offset, ch),
        )

    @kernel
    def set_freq(self, ch: np.int32, freq):
        """
        Frequency is in Hz
        """
        self.set_dds(ch, freq, self.offsets[ch])

    @kernel
    def set_offset(self, ch: np.int32, offset):
        """
        Offset is in V
        """
        self.set_dds(ch, self.freqs[ch], offset)

    @kernel
    def set_y(self, ch: np.int32, y):
        self._mutate_and_set_float("ys", self.ys, ch, y)

        self.core.break_realtime()
        self.channels[ch].set_y(profile=ch, y=y)

    @kernel
    def set_iir(self, ch: np.int32, adc, P, I, Gl):  # noqa: E741
        self._mutate_and_set_float("Ps", self.Ps, ch, P)
        self._mutate_and_set_float("Is", self.Is, ch, I)
        self._mutate_and_set_float("Gls", self.Gls, ch, Gl)

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
        delay(10 * us)
        self.set_y(ch, self.ys[ch])

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

        for ch in range(8):
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
            # set attenuation on all 4 channels -
            # we set all from the dataset then overwrite the one we want
            self.suservo.cplds[ch // 4].set_att(ch % 4, self.atts[ch])
            self.channels[ch].set(
                en_out=self.en_outs[ch], en_iir=self.en_iirs[ch], profile=ch
            )
            delay(5 * 1.2 * us)

        self.suservo.set_config(enable=self.enabled)
