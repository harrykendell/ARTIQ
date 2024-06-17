from artiq.experiment import *

class SUServoMinimal(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("urukul0_cpld")
        self.setattr_device("suservo")
        self.setattr_device("suservo_ch0")

        self.setattr_argument("en_irr", BooleanValue(True))

    @kernel
    def run(self):
        # Prepare core
        self.core.reset()

        # Initialize and activate SUServo
        self.suservo.init()
        self.suservo.set_config(enable=1)

        # Set Sampler gain and Urukul attenuation
        gain = 0
        attenuation = 0.0
        # set gain on Sampler channel 0 to 10^gain
        self.suservo.set_pgia_mu(0, gain)
        # set attenuation on Urukul channel 0 to A
        self.suservo.cpld0.set_att(0, attenuation)

        # Set physical parameters
        targetV = 1.0  # target input voltage (V) for Sampler channel
        freq = 100e6  # frequency (Hz) of Urukul output
        # offset to assign to servo to reach target voltage
        offset = -targetV * (10.0 ** (gain - 1))

        self.suservo_ch0.set_dds(profile=0, frequency=freq, offset=offset)

        # Input parameters, activate Urukul output (en_out=1), activate PI loop (en_iir=1)

        if self.en_irr:
            # Set PI loop parameters
            P = 0.005  # proportional gain in loop
            I = -10.0  # integrator gain
            gl = 0.0  # integrator gain limit
            adc_ch = 0  # Sampler channel to read from

            self.suservo_ch0.set(en_out=1, en_iir=1, profile=0)
            self.suservo_ch0.set_iir(profile=0, adc=adc_ch, kp=P, ki=I, g=gl)
        else:
            self.suservo_ch0.set_y(0, 1.0)
            self.suservo_ch0.set(en_out=1, en_iir=0, profile=0)
