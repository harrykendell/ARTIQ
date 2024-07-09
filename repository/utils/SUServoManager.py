from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay, TInt64

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel, COEFF_WIDTH

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
        suservo_chs: SUServoChannel,
        name="suservo",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.suservo: SUServo = suservo
        self.channels: SUServoChannel = suservo_chs
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
            "sampler_chs",
        ]
        defaults = [
            1,
            [0] * 8,
            [31.5] * 8,
            [200e6] * 8,
            [1] * 8,
            [1.0] * 8,
            [0] * 8,
            [0.0] * 8,
            [-0.005] * 8,
            [-10.0] * 8,
            [0.0] * 8,
            [i for i in range(8)],
        ]
        units = [None, "dB", "dB", "MHz", None, None, None, "FullScale", None, None, None, None]
        for dataset, default, unit in zip(datasets, defaults, units):
            temp = experiment.get_dataset(
                name + "." + dataset, default=default, archive=False
            )
            # we set the values back so we are allowed to mutate then later
            experiment.set_dataset(
                name + "." + dataset,
                temp,
                persist=True,
                archive=False,
                unit=unit,
            )
            self.__dict__[dataset] = temp
        
        self.set_all()

    @kernel
    def get_adc(self, ch):
        '''
        Get the ADC value for a given channel
        Delays by 20us to ensure the servo was disabled
        '''
        self.suservo.set_config(0)
        delay(10*us)
        v = self.channels[ch].get_adc(0)
        self.suservo.set_config(self.enabled)
        delay(10*us)
        return v
    
    @kernel
    def _mutate_and_set_float(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50*ms)

    @kernel
    def _mutate_and_set_int(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50*ms)

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

        self.core.break_realtime()

        # We have to write all 4 channels at once
        for i in range(4):
            self.suservo.cplds[ch // 4].set_att(i, self.atts[i if ch < 4 else 4 + i])

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

        self.channels[ch].set_dds(profile=0, frequency=freq * MHz, offset=self.offsets[ch])

    @kernel
    def set_y(self, ch, y):
        self._mutate_and_set_float("ys", self.ys, ch, y)

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

    @kernel
    def set_all(self):
        """
        Ensures the SUServo is set to the current state of the manager
        Where possible we extract state from the SUServo and update the dataset
        """

        # Prepare core
        self.core.reset()
        self.core.break_realtime()

        self.enabled = self.suservo.get_status() & 0b01
        delay(200 * ms)
        self.experiment.set_dataset(
            self.name + ".enabled", self.enabled, persist=True, archive=False
        )
        delay(100 * ms)
        # Initialize SUServo - this will leave it disabled
        self.suservo.init()
        delay(10 * ms)

        buffer = [0] * 8
        for ch in range(8):
            self.channels[ch].get_profile_mu(0, buffer)
            delay(100*us)
            self._mutate_and_set_float("offsets", self.offsets, ch, buffer[4] / (1 << COEFF_WIDTH - 1))
            self._mutate_and_set_int("sampler_chs", self.sampler_chs, ch, buffer[3] & 0xFF)
            self._mutate_and_set_float(
                "freqs",
                self.freqs,
                ch,
                self.suservo.ddses[0].ftw_to_frequency(buffer[0] << 16 | buffer[6]),
            )
            self._mutate_and_set_float("ys", self.ys, ch, self.channels[ch].get_y(0))
            self.core.break_realtime()
            # set gain on Sampler channel  to 10^gain - these are wiped in the init
            self.suservo.set_pgia_mu(ch, self.gains[ch])

            # offset to assign to servo to reach target voltage - negative to lock to a positive reference
            offset = -self.offsets[ch] * (10.0 ** (self.gains[ch] - 1))
            # Set profile parameters
            self.channels[ch].set_dds(
                profile=0, frequency=self.freqs[ch], offset=offset
            )
            delay(200 * us)
            # PI loop params
            self.channels[ch].set_iir(
                profile=0,
                adc=self.sampler_chs[ch],
                kp=self.Ps[ch],
                ki=self.Is[ch],
                g=self.Gls[ch],
            )

            self.channels[ch].set_y(profile=0, y=self.ys[ch])

        for ch in range(8):
            # set attenuation on all 4 channels - we set all from the dataset then overwrite the one we want
            self.suservo.cplds[ch // 4].set_att(ch % 4, self.atts[ch])
            self.channels[ch].set(
                en_out=self.en_outs[ch], en_iir=self.en_iirs[ch], profile=0
            )
            delay(5 * 1.2 * us)

        self.suservo.set_config(enable=self.enabled)
