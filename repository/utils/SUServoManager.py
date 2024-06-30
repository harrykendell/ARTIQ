from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel

class SUServoManager(): #{{{
    """
    Manages a single SUServo device with 8 channels

    It tries to load the state from the dataset provided, if it doesn't exist it will create a new one
    """

    def __init__(self, experiment: EnvExperiment, core: Core, suservo: SUServo, suservo_chs: SUServoChannel, name='suservo'):
        self.experiment = experiment
        self.core: Core = core
        self.suservo: SUServo = suservo
        self.channels: SUServoChannel = suservo_chs
        self.name = name

        assert len(self.channels) == 8, "There must be 8 channels per SUServo"

        datasets = ["enabled", "gains", "atts",   "freqs",     "en_outs", "ys",     "en_iirs", "Vs",    "Ps",      "Is",      "Gls",   "sampler_ch"]
        defaults = [1,         [0]*8,   [31.5]*8, [200e6]*8,   [1]*8,     [1.0]*8,  [0]*8,     [0.0]*8, [-0.005]*8, [-10.0]*8, [0.0]*8, [i for i in range(8)]]
        units =    [None,      "dB",    "dB",     "MHz",       None,      None,     None,      "V",     None,       None,       None,    None]
        for dataset,default,unit in zip(datasets,defaults,units):
            self.__dict__[dataset] = experiment.get_dataset(name+"."+dataset, default=default, archive=False)
            # we set the values back so we are allowed to mutate then later
            experiment.set_dataset(name+"."+dataset, self.__dict__[dataset], persist=True, archive=False, unit=unit)

        self.set_all()

    @kernel
    def _mutate_and_set(self, dataset, variable, index, value):
        '''Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as __dict__ access is illegal on kernel
        '''
        self.experiment.mutate_dataset(self.name+"."+dataset, index, value)
        variable[index] = value

    @kernel
    def enable_servo(self):
        self.experiment.set_dataset(self.name+".enabled", 1, persist=True, archive=False)
        self.enabled= 1
        self.core.break_realtime()
        self.suservo.set_config(enable=1)

    @kernel
    def disable_servo(self):
        self.experiment.set_dataset(self.name+".enabled", 0, persist=True, archive=False)
        self.enabled= 0
        self.core.break_realtime()
        self.suservo.set_config(enable=0)

    @kernel
    def enable(self, ch):
        """Enable a given channel"""
        self._mutate_and_set("en_outs", self.en_outs, ch, 1)
        self.core.break_realtime()
        self.channels[ch].set(1,self.en_iirs[ch],ch)

    @kernel
    def disable(self, ch):
        """Disable a given channel"""
        self._mutate_and_set("en_outs", self.en_outs, ch, 0)
        self.core.break_realtime()
        self.channels[ch].set(0,0,0)

    @kernel
    def set_gain(self, ch, gain):
        self._mutate_and_set("gains", self.gains, ch, gain)
        self.core.break_realtime()
        self.suservo.set_pgia_mu(ch, gain)

    @kernel
    def set_att(self, ch, att):
        self._mutate_and_set("atts", self.atts, ch, att)

        self.core.break_realtime()
        # # Disable our profile to avoid collisions, 31 should be kept clean for this
        self.channels[ch].set(en_out=self.en_outs[ch], en_iir=self.en_iirs[ch], profile=31)
        delay(2*1.2*us)

        # We have to write all 4 channels at once
        for i in range(4):
            self.suservo.cplds[ch//4].set_att(i, self.atts[i if ch<4 else 4+i])

        # set back the one we want
        self.channels[ch].set(en_out=self.en_outs[ch], en_iir=self.en_iirs[ch], profile=ch)
        delay(2*1.2*us)

    @kernel
    def set_dds(self, ch, freq, V):
        offset = -V * (10.0 ** (self.gains[ch] - 1))
        self._mutate_and_set("freqs", self.freqs, ch, freq)
        self._mutate_and_set("Vs", ch, offset)

        self.core.break_realtime()

        self.channels[ch].set_dds(profile=ch, frequency=freq*MHz, offset=offset)

    @kernel
    def set_freq(self, ch, freq):
        self._mutate_and_set("freqs", self.freqs, ch, freq*MHz)

        self.core.break_realtime()

        self.channels[ch].set_dds(profile=ch, frequency=freq*MHz, offset=self.Vs[ch])

    @kernel
    def set_y(self, ch, y):
        self._mutate_and_set("ys", self.ys, ch, y)

        self.core.break_realtime()
        self.channels[ch].set_y(profile=ch, y=y)

    @kernel
    def set_iir(self, ch, adc, P, I, Gl):
        self._mutate_and_set("sampler_ch", ch, adc)
        self._mutate_and_set("Ps", ch, P)
        self._mutate_and_set("Is", ch, I)
        self._mutate_and_set("Gls", ch, Gl)

        self.core.break_realtime()

        self.channels[ch].set_iir(profile=ch, adc=adc, kp=P, ki=I, g=Gl)

    @kernel
    def set_all(self):
        """
        Ensures the SUServo is set to the current state of the manager

        we can retrieve
        get_y: y
            y - the output scaling amplitude
        get_profile_mu: [ftw >> 16, b1, pow, adc | (delay << 8), offset, a1,ftw & 0xffff, b0]
            ftw >> 16           - frequency tuning word
            b1                  - feedforward gain
            pow                 - phase offset word
            adc | (delay << 8)  - adc channel | delay until implementation
            offset              - negative setpoint offset
            a1                  - feedback gain
            ftw & 0xffff        - frequency tuning word
            b0                  - feedforward gain
        get_status: Bit 0: enabled, bit 1: done, bits 8-15: channel clip indicators.

        so we should be able to retrieve the state up to gains and atts
        ["enabled", "gains", "atts",   "freqs",     "en_outs", "ys",     "en_iirs", "Vs",    "Ps",      "Is",      "Gls",   "sampler_ch"]

        """

        # Prepare core
        print("Resetting core")
        self.core.reset()
        self.core.break_realtime()

        # Initialize SUServo
        self.suservo.init()
        delay(10*ms)

        for ch in range(8):
            # set gain on Sampler channel  to 10^gain
            self.suservo.set_pgia_mu(ch, self.gains[ch])

            # Disable our profile to avoid collisions, 31 should be kept clean for this
            self.channels[ch].set(en_out=0, en_iir=0, profile=31)
            delay(2*1.2*us)

            # offset to assign to servo to reach target voltage - negative to lock to a positive reference
            offset = -self.Vs[ch] * (10.0 ** (self.gains[ch] - 1))
            # Set profile parameters - this must be done with the servo disabled or another profile enabled
            self.channels[ch].set_dds(profile=ch, frequency=self.freqs[ch], offset=offset)

            # Input parameters, activate Urukul output (en_out=1), activate PI loop (en_iir=1)
            self.channels[ch].set_iir(profile=ch, adc=self.sampler_ch[ch], kp=self.Ps[ch], ki=self.Is[ch], g=self.Gls[ch])
            if not self.en_iirs[ch]:
                self.channels[ch].set_y(profile=ch, y=self.ys[ch])

        for ch in range(8):
            # set attenuation on all 4 channels - we set all from the dataset then overwrite the one we want
            self.suservo.cplds[ch//4].set_att(ch%4, self.atts[ch])
            self.channels[ch].set(en_out=self.en_outs[ch], en_iir=self.en_iirs[ch], profile=ch)
            delay(2*1.2*us)

        self.suservo.set_config(enable=self.enabled)
        print("SUServo set")
