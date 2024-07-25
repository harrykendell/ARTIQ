from artiq.experiment import *
from artiq.language.units import dB, ms, us, MHz, GHz
from artiq.language.core import kernel, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel
from artiq.coredevice.mirny import Mirny
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.almazny import AlmaznyChannel


class Laser780(EnvExperiment):
    """
    Setup 780nm laser.

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
        self.setattr_device("urukul0_cpld")
        self.suservo: SUServo
        self.setattr_device("suservo_aom_780_locking")
        self.suservo_aom_780_locking: SUServoChannel
        self.setattr_device("suservo_aom_780_MOT")
        self.suservo_aom_780_MOT: SUServoChannel

        self.setattr_device("mirny_cpld")
        self.mirny_cpld: Mirny
        self.setattr_device("mirny_eom_780")
        self.mirny_eom_780: ADF5356
        self.setattr_device("almazny_eom_780")
        self.almazny_eom_780: AlmaznyChannel

        self.channels = [self.suservo_aom_780_locking, self.suservo_aom_780_MOT]

        self.setattr_argument(
            "eom_frequency",
            NumberValue(default=7.072e9, precision=3, step=0.001, unit="GHz"),
            group="780nm",
            tooltip="[GHz] | Frequency output on Almazny CH0",
        )
        self.setattr_argument(
            "aom_locking_frequency",
            NumberValue(default=80e6, precision=3, step=0.001, unit="MHz"),
            group="780nm",
            tooltip="[MHz] | Frequency output on Urukul CH0",
        )
        self.setattr_argument(
            "aom_MOT_frequency",
            NumberValue(default=200e6, precision=3, step=0.001, unit="MHz"),
            group="780nm",
            tooltip="[MHz] | Frequency output on Urukul CH1",
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
        self.suservo.cplds[0].set_att(0, attenuation)

        # Set physical parameters
        targetV = 1.0  # target input voltage (V) for Sampler channel

        # offset to assign to servo to reach target voltage
        offset = -targetV * (10.0 ** (gain - 1))

        self.suservo_aom_780_locking.set_dds(
            profile=0, frequency=self.aom_locking_frequency, offset=offset
        )

        # Input parameters, activate Urukul output (en_out=1), activate PI loop (en_iir=1)

        self.suservo_aom_780_locking.set_y(0, 1.0)
        self.suservo_aom_780_locking.set(en_out=1, en_iir=0, profile=0)

        # gain = 0 #settings 0,1,2,3 approx 1,10,100,1000
        # attenuation = 0.0

        # self.core.reset()

        # self.suservo.init()
        # delay(1 * us)

        # # ADC PGIA gain 0
        # for i in range(8):
        #     self.suservo.set_pgia_mu(i, gain)
        #     delay(10 * us)

        #     # DDS attenuator 0.0dB
        #     for cpld in self.suservo.cplds:
        #         cpld.set_att(i, attenuation)
        # delay(1 * us)

    @kernel
    def set_AOM(self, channel, freq, att, enable, num):

        # we need to transiently disable the servo to avoid glitches
        channel.servo.set_config(enable=1)

        # setpoint 0.5 (5 V with above PGIA gain setting)
        delay(100 * us)
        channel.set_dds(
            profile=num, offset=0.0, frequency=freq  # 3 V with above PGIA settings
        )

        channel.set_iir(
            profile=num,
            adc=num,  # take data from Sampler channel
            kp=-1.0,  # -1 P gain
            ki=0.0,  # no integrator gain
            g=0.0,  # no integrator gain limit
            delay=0.0,  # no IIR update delay after enabling
        )
        delay(1 * us)
        channel.set_y(profile=num, y=1.0)  # clear integrator

        delay(100 * us)
        channel.servo.cplds[num].set_att(num, att)

        # enable RF, IIR updates and set profile
        delay(10 * us)
        channel.set(en_out=enable, en_iir=0, profile=num)

        # we can now re-enable the servo
        self.core.break_realtime()
        channel.servo.set_config(enable=1)

    @kernel
    def set_AOMs(self, frequencies, attenuations, enable):
        """
        Set the AOMs for the 780nm laser using
        the SUServo Urukul channels.
        """
        self.core.break_realtime()

        for num in range(len(self.channels)):
            print("Setting AOM", num, "to", frequencies[num] / 1e6, "MHz")
            self.set_AOM(
                self.channels[num],
                frequencies[num],
                attenuations[num],
                enable[num],
                num,
            )

    @kernel
    def set_EOM(self, frequency=-1.0, attenuation=0 * dB, enable=False):
        """
        Set the frequency of the EOM.
        Almazny frequency = frequency
        Mirny frequency = frequency/2.0
        """
        if frequency == -1.0:
            frequency = self.eom_frequency

        self.core.break_realtime()
        # Disable the output momentarily to avoid sending the wrong settings
        # at any point
        self.mirny_eom_780.sw.off()

        delay(100 * ms)
        print("Setting EOM frequency to", frequency / 1e9, "GHz")
        self.mirny_eom_780.set_frequency(frequency / 2.0)
        self.mirny_eom_780.set_att(attenuation)

        self.mirny_eom_780.sw.set_o(enable)
        self.almazny_eom_780.set(attenuation, enable, enable)

    @kernel
    def run(self):
        self.core.reset()

        self.init_EOM()
        self.set_EOM()

        self.init_AOMs()
        # self.set_AOMs(
        #     frequencies=[self.aom_locking_frequency, self.aom_MOT_frequency],
        #     attenuations=[0.0, 0.0],
        #     enable=[0, 0],
        # )

    def main(self):
        return
