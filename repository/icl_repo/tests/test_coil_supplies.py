import logging

from artiq.coredevice.core import Core
from artiq.coredevice.zotino import Zotino
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from device_db_config import get_configuration_from_db
from icl_repo.lib.fragments.current_supply_setter import SetAnalogCurrentSupplies

logger = logging.getLogger(__name__)


class SetZotinoVoltage(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("zotino_plant_room")
        self.zotino_plant_room: Zotino

        self.setattr_argument(
            "channel", NumberValue(default=0, precision=0, step=1, scale=1, type="int")
        )
        self.setattr_argument("voltage", NumberValue(default=0.0, unit="V"))

    @kernel
    def run(self):
        self.core.reset()
        self.zotino_plant_room.init()
        delay(200e-6)
        self.zotino_plant_room.set_dac([0.0] * 32)
        delay(200e-6)
        self.zotino_plant_room.set_dac([self.voltage], [self.channel])


class RampGradientCoilsFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        current_config_mot = get_configuration_from_db("chamber_2_coil_mot")

        self.setattr_fragment(
            "current_setter_mot",
            SetAnalogCurrentSupplies,
            current_configs=[current_config_mot],
        )
        self.current_setter_mot: SetAnalogCurrentSupplies

        self.setattr_param(
            "duration",
            FloatParam,
            "Duration of phase",
            default=1.0,
            min=0.0,
            unit="ms",
        )

        self.setattr_param(
            "start_gradient",
            FloatParam,
            description="Initial gradient current",
            default=0.0,
            min=0.0,
            unit="A",
        )
        self.setattr_param(
            "end_gradient",
            FloatParam,
            description="Final gradient current",
            default=10.0,
            min=0.0,
            unit="A",
        )
        self.setattr_param(
            "ramp_step",
            FloatParam,
            description="Time step between ramp steps",
            default=1 / 75e3,
            min=0.0,
            unit="us",
        )

        self.setattr_param(
            "slack_before_ramp",
            FloatParam,
            description="How much slack to create before queuing the ramp",
            default=1.0,
            min=0.0,
            unit="s",
        )

        self.duration: FloatParamHandle
        self.start_gradient: FloatParamHandle
        self.end_gradient: FloatParamHandle
        self.slack_before_ramp: FloatParamHandle
        self.ramp_step: FloatParamHandle

    @kernel
    def run_once(self):
        logger.info("Starting ramp")

        self.core.break_realtime()
        delay(self.slack_before_ramp.get())

        self.current_setter_mot.set_currents_ramping(
            currents_start=[self.start_gradient.get()],
            currents_end=[self.end_gradient.get()],
            duration=self.duration.get(),
            ramp_step=self.ramp_step.get(),
        )

        logger.info("Ramp completed")


RampGradientCoils = make_fragment_scan_exp(RampGradientCoilsFrag)
