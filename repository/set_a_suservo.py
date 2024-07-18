from artiq.experiment import *
from artiq.language import delay, ms, us
from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel

class SUServoControl(EnvExperiment):
    '''Control of all SUServo channels
    
    records attenuations in a dataset due to the inability to restore them from the device.'''
    
    def build(self):
        self.core: Core = self.get_device("core")
        self.suservo: SUServo = self.get_device("suservo")

        self.setattr_argument("Initialise", BooleanValue(False),tooltip="Initialise SUServo", group="SUServo") #SUServo.init

        # SUServo parameters
        self.setattr_argument("Enable", BooleanValue(True),tooltip="Enable SUServo", group="SUServo") #SUServo.set_config
        self.En = 1 if self.Enable else 0

        # Channel parameters
        self.setattr_argument("Channel", NumberValue(0, min=0, max=7, precision=0, step=1,type='int'),tooltip="Channel to use for the DDS", group="Channel")
        self.setattr_argument("Gain", NumberValue(0, min=0, max = 3, precision=0, step=1, type='int'),tooltip="Gain of Sampler channel", group="Channel") #SUServo.set_pgia_mu
        self.setattr_argument("Attenuation", NumberValue(0.0, min=0.0, max=31.5, step=0.5, unit = 'dB'),tooltip="Attenuation of Urukul output", group="Channel") #urukul_CPLD.set_att

        # Profile parameters
        # The PROFILE pins are common to all four DDS channels.
        self.setattr_argument("Profile", NumberValue(0, min=0, max=31, precision=0,step=1, type='int'),tooltip="Profile to use for the DDS", group="Profile")

        self.setattr_argument("Frequency", NumberValue(100e6, unit="MHz", min=50e5, step=1e5),tooltip="Frequency of Urukul output", group="Profile") #SUServoChannel.set_dds
        self.setattr_argument("EnableOut", BooleanValue(True),tooltip="Enable Urukul output", group='Profile') #SUServoChannel.set
        self.EnOut = 1 if self.EnableOut else 0
        self.setattr_argument("OutputScale", NumberValue(1.0, min=0.0, max=1.0),tooltip="Output scale of the servo", group='Profile') #SUServoChannel.set_y
        
        self.setattr_argument("EnableIIR", BooleanValue(False),tooltip="Enable IIR loop - i.e. the PI loop", group='IIR') #SUServoChannel.set
        self.EnIIR = 1 if self.EnableIIR else 0
        self.setattr_argument("TargetV", NumberValue(0.0, unit="V", step=0.01),tooltip="Setpoint for the servo", group="IIR") #SUServoChannel.set_dds_offset

        self.setattr_argument("P", NumberValue(-0.005, min=-1.0, max=1.0),tooltip="Proportional gain in loop (-ve for closed loop)", group='IIR') #SUServoChannel.set_iir
        self.setattr_argument("I", NumberValue(-10.0, min=-100.0, max=100.0),tooltip="Integrator gain (same sign as P)", group='IIR') #SUServoChannel.set_iir
        self.setattr_argument("Gl", NumberValue(0.0, min=0.0, max=100.0),tooltip="Integrator gain limit (0->inf)", group='IIR') #SUServoChannel.set_iir
        self.setattr_argument("SamplerChannel", NumberValue(0, min=0, max=7, precision=0, step=1,type='int'),tooltip="Sampler channel to read from", group='IIR') #SUServoChannel.set_iir

        self.suservo_ch: SUServoChannel = self.get_device(f"suservo_ch{self.Channel}")
        self.Attenuations = self.get_dataset("suservo.atts", default=[20.0]*8, archive=False)

    @kernel
    def run(self):
        
        # Prepare core
        self.core.reset()
        self.core.break_realtime()

        # Initialize and activate SUServo
        if self.Initialise:
            self.suservo.init()
            delay(10*ms)

        # set gain on Sampler channel  to 10^gain
        self.suservo.set_pgia_mu(self.Channel, self.Gain)

        # Disable our profile to avoid collisions, 31 should be kept clean for this
        self.suservo_ch.set(en_out=0, en_iir=0, profile=31)
        delay(2*1.2*us)

        # set attenuation on all 4 channels - we set all from the dataset then overwrite the one we want
        reg = 0
        for i in range(4):
            if i==self.Channel%4:
                reg += self.suservo.cplds[0].att_to_mu(self.Attenuation) << (i * 8)
            else:
                reg += self.suservo.cplds[0].att_to_mu(self.Attenuations[i if self.Channel < 4 else 4 + i]) << (i * 8)
            
        self.core.break_realtime()
        self.suservo.cplds[self.Channel // 4].set_all_att_mu(reg)

        # offset to assign to servo to reach target voltage - negative to lock to a positive reference
        offset = -self.TargetV * (10.0 ** (self.Gain - 1))
        # Set profile parameters - this must be done with the servo disabled or another profile enabled
        self.suservo_ch.set_dds(profile=self.Profile, frequency=self.Frequency, offset=offset)

        # Input parameters, activate Urukul output (en_out=1), activate PI loop (en_iir=1)
        self.suservo_ch.set_iir(profile=self.Profile, adc=self.SamplerChannel, kp=self.P, ki=self.I, g=self.Gl)
        if not self.EnIIR:
            self.suservo_ch.set_y(profile=self.Profile, y=self.OutputScale)

        self.suservo_ch.set(en_out=self.EnOut, en_iir=self.EnIIR, profile=self.Profile)
        delay(2*1.2*us)

        self.suservo.set_config(enable=self.En)