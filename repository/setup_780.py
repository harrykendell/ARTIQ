from artiq.experiment import *
from artiq.language.units import dB, ms, us, MHz
from artiq.language.core import kernel, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel
from artiq.coredevice.mirny import Mirny
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.almazny import AlmaznyChannel

class Laser780(EnvExperiment):
    """
    This sets up a GUI for the 780nm laser to control a number of AOMs and a single EOM.
    It aims for the default frequencies with ramping and locking.

    The GUI uses worker_db.py components to manage its own experiment submissions

    Components:
        1 AOM at xMHz using a SUServo Urukul channel
            - Laser locking offset
        1 AOM at xMHz using a SUServo Urukul channel
            - 2/3D MOT offset
        2 Booster channels
            - AOMs
    """

    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("suservo")
        self.suservo: SUServo
        self.setattr_device("suservo_aom_780_locking")
        self.suservo_aom_780_locking: SUServoChannel
        self.setattr_device("suservo_aom_780_MOT")
        self.suservo_aom_780_MOT: SUServoChannel

        self.setattr_device("mirny_cpld")
        self.mirny_cpld: Mirny
        self.setattr_device("mirny_eom_780")
        self.mirny_eom_780: ADF5356
        self.setattr_device("almazny_rom_780")
        self.almazny_eom_780: AlmaznyChannel

        self.channels = [self.suservo_aom_780_locking, self.suservo_aom_780_MOT]

        self.setattr_argument(
            "frequency",
            NumberValue(unit="GHz", default=7.072, min=0, max=10),
            tooltip="Frequency of the EOM",
        )

        self.setattr_argument(
            "en_irr", BooleanValue(True), tooltip="Enable IIR loop - i.e. the PI loop"
        )

    @kernel
    def init_EOM(self):
        """
        Initialize the EOM for the 780nm laser using
        the Mirny DDS with Almazny mezzanine.
        """
        self.core.break_realtime()

        self.mirny_cpld.init()
        self.mirny_eom_780.init()

    @kernel
    def init_AOMs(self):
        """
        Initialize the AOMs for the 780nm laser using
        the SUServo Urukul channels.
        """
        self.core.break_realtime()

        self.suservo.init()
        delay(1 * us)

        # ADC PGIA gain 0
        for i in range(8):
            self.suservo.set_pgia_mu(i, 0)
            delay(10 * us)

        # DDS attenuator 0.0dB
        for i in range(4):
            for cpld in self.suservo.cplds:
                cpld.set_att(i, 0.0)
        delay(1 * us)

    @kernel
    def set_AOM(self, channel: SUServoChannel, freq: float, att: float, enable: bool, num: int):

        # we need to transiently disable the servo to avoid glitches
        channel.servo.set_config(enable=0)

        channel.set_y(profile=num, y=1.0)  # clear integrator

        channel.set_iir(
            profile=num,
            adc=num,  # take data from Sampler channel
            kp=-1.0,  # -1 P gain
            ki=0.0,  # no integrator gain
            g=0.0,  # no integrator gain limit
            delay=0.0,  # no IIR update delay after enabling
        )

        # setpoint 0.5 (5 V with above PGIA gain setting)
        delay(100 * us)
        channel.set_dds(
            profile=num,
            offset=-0.3,  # 3 V with above PGIA settings
            frequency=freq,
            phase=0.0,
        )

        delay(100 * us)
        channel.servo.cplds[num].set_att(num, att)

        # enable RF, IIR updates and set profile
        delay(10 * us)
        channel.set(en_out=enable, en_iir=0, profile=num)

        # we can now re-enable the servo
        self.core.break_realtime()
        channel.servo.set_config(enable=1)

    @kernel
    def set_AOMs(self, frequencies: list[float] = None, attenuations: list[float] = None, enable: list[bool] = None):
        """
        Set the AOMs for the 780nm laser using
        the SUServo Urukul channels.
        """
        self.core.break_realtime()

        for num in range(len(self.channels)):
            self.set_AOM(self.channels[num], frequencies[num], attenuations[num], enable[num], num)

    @kernel
    def set_EOM(self, frequency: float = None, attenuation: float = 0*dB, enable: bool = True):
        """
        Set the frequency of the EOM.
        Almazny frequency = frequency
        Mirny frequency = frequency/2.0
        """
        freq = frequency if frequency else self.frequency

        # Disable the output momentarily to avoid sending the wrong settings
        # at any point
        self.mirny_eom_780.sw.set_o(False)

        self.mirny_eom_780.set_frequency(frequency/2.0)
        self.mirny_eom_780.set_att(attenuation)

        self.mirny_eom_780.sw.set_o(enable)
        self.almazny_eom_780.set(attenuation, enable, enable)

    @kernel
    def run(self):
        self.core.reset()

        self.init_EOM()
        self.set_EOM()

    def main(self):
        return
