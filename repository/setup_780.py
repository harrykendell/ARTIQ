from artiq.experiment import *
from artiq.coredevice.core import Core
from artiq.coredevice.urukul import CPLD as urukul_CPLD
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel

class Laser780(EnvExperiment):
    '''
        This sets up a GUI for the 780nm laser to control a number of AOMs and a single EOM.
        It aims for the default frequencies with ramping and locking.

        The GUI uses worker_db.py components to manage its own experiment submissions

        Components:
            1 EOM at 7.8GHz using a Mirny DDS with Almazny mezzanine
                - Sidebands for repump
            1 AOM at xMHz using a SUServo Urukul channel
                - Laser locking offset
            1 AOM at xMHz using a SUServo Urukul channel
                - 2/3D MOT offset
            2 Booster channels
                - AOMs
    '''
    def build(self):
        self.setattr_device("core")
        self.core: Core
        self.setattr_device("urukul0_cpld")
        self.urukul0_cpld: urukul_CPLD
        self.setattr_device("suservo")
        self.suservo: SUServo
        self.setattr_device("suservo_ch0")
        self.suservo_ch0: SUServoChannel

        self.setattr_argument("en_irr", BooleanValue(True),tooltip="Enable IIR loop - i.e. the PI loop")

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
        # set attenuation on Urukul channel 0
        self.urukul0_cpld.set_att(0, attenuation)

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
