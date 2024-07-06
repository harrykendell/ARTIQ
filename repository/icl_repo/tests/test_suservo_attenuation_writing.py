import logging

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.coredevice.suservo import SUServo
from artiq.coredevice.urukul import *
from artiq.coredevice.urukul import CPLD
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import StringValue

logger = logging.getLogger(__name__)


class TestSUServoAttenuationReading(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_argument(
            "channel_name",
            StringValue(default="suservo_aom_singlepass_689_red_mot_diagonal"),
        )

        self.suservo_channel: SUServoChannel = self.get_device(self.channel_name)

    def prepare(self):
        self.suservo: SUServo = self.suservo_channel.servo

    @kernel
    def run(self):
        self.core.break_realtime()
        self.suservo.init()

        cpld = self.suservo_channel.dds.cpld  # type: CPLD
        att_mu = cpld.get_att_mu()

        logger.info("att_mu = %d", att_mu)

        self.core.break_realtime()
        self.set_this_attenuation(10.0)

        att_mu = cpld.get_att_mu()
        logger.info("att_mu = %d", att_mu)

        self.core.break_realtime()
        self.set_this_attenuation(20.0)

        att_mu = cpld.get_att_mu()
        logger.info("att_mu = %d", att_mu)

    @kernel
    def set_this_attenuation(self, attenuation: TFloat):
        # Set the attenuator for this channel on this Urukul
        attenuator_channel = self.suservo_channel.servo_channel % 4
        cpld = self.suservo_channel.dds.cpld  # type: CPLD
        cpld.set_att(attenuator_channel, attenuation)
