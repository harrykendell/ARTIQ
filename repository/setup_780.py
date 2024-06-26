from artiq.experiment import *
from artiq.coredevice.core import Core
from artiq.coredevice.urukul import CPLD as urukul_CPLD
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel
from artiq.coredevice.mirny import Mirny
from artiq.coredevice.almazny import AlmaznyChannel

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
        self.setattr_device("almazny_ch0")
        self.almazny: AlmaznyChannel

        self.setattr_argument("en_irr", BooleanValue(True),tooltip="Enable IIR loop - i.e. the PI loop")

    @kernel
    def run(self):
        return
    
    def main(self):
        return
