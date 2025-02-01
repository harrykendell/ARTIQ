import logging

import numpy as np
from artiq.coredevice.core import Core
from artiq.coredevice.suservo import Channel
from artiq.coredevice.suservo import SUServo
from artiq.experiment import BooleanValue
from artiq.experiment import EnumerationValue
from artiq.experiment import EnvExperiment
from artiq.experiment import NumberValue
from artiq.experiment import TBool
from artiq.experiment import TFloat
from artiq.experiment import kernel
from artiq.experiment import now_mu
from repository.utils.get_local_devices import get_local_devices

logger = logging.getLogger(__name__)

DATASET_KEY_T = "suservo_tuning_t"
DATASET_KEY_V = "suservo_tuning_v"
DATASET_KEY_V_ERR_HACK = "suservo_tuning_v_err_hack"


class TuneSUServo(EnvExperiment):
    """
    Tune a SUServo output
    """

    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_argument(
            "channel_name", EnumerationValue(get_local_devices(self, Channel))
        )
        self.channel_name: str
        self.setattr_argument(
            "adc_channel",
            NumberValue(default=0, scale=1, precision=0, step=1, type="int"),
        )
        self.adc_channel: int

        self.setattr_argument(
            "frequency",
            NumberValue(default=100e6, precision=1, type="float", unit="MHz"),
        )
        self.frequency: float

        self.setattr_argument(
            "attenuation",
            NumberValue(default=30.0, precision=1, type="float", unit="dB"),
        )
        self.attenuation: float

        self.setattr_argument(
            "amplitude",
            NumberValue(default=1.0, precision=1, type="float", min=0, max=1),
        )
        self.amplitude: float

        self.setattr_argument(
            "num_points",
            NumberValue(default=0, scale=1, precision=0, step=1, type="int"),
        )
        self.num_points: int

        self.setattr_argument("enable_iir", BooleanValue(default=False))
        self.enable_iir: bool

        self.setattr_argument(
            "kp",
            NumberValue(default=1.0, precision=5, type="float"),
        )
        self.setattr_argument(
            "ki",
            NumberValue(default=0.0, precision=5, type="float"),
        )
        self.setattr_argument(
            "gain_limit",
            NumberValue(default=0.0, precision=1, type="float"),
        )
        self.setattr_argument(
            "delay",
            NumberValue(default=0.0, precision=1, type="float", unit="us"),
        )
        self.setattr_argument(
            "setpoint",
            NumberValue(default=1.0, precision=3, type="float", unit="V"),
        )
        self.kp: float
        self.ki: float
        self.gain_limit: float
        self.delay: float
        self.setpoint: float

        self.setattr_device("ccb")

    def prepare(self):
        self.suservo_channel: Channel = self.get_device(self.channel_name)
        self.suservo: SUServo = self.suservo_channel.servo

        cmd = f"${{artiq_applet}}plot_xy {DATASET_KEY_V} --x {DATASET_KEY_T} --fit {DATASET_KEY_V} --error {DATASET_KEY_V_ERR_HACK}"

        self.ccb.issue("create_applet", "SUServo tuning", cmd)

    @kernel
    def run(self):
        # Initiate the suservo itself (i.e. all four channels)

        self.core.reset()
        self.suservo.init()
        self.suservo.set_config(enable=1)

        self.set_all_attenuations(self.attenuation)
        self.set_this_attenuation(self.attenuation)

        self.set_dds_params(
            self.frequency, self.amplitude, False, setpoint_v=self.setpoint
        )
        self.suservo_channel.set_iir(
            self.adc_channel,
            self.adc_channel,
            self.kp,
            self.ki,
            self.gain_limit,
            self.delay,
        )

        self.suservo_channel.set(
            en_out=1, en_iir=(1 if self.enable_iir else 0), profile=self.adc_channel
        )

        t_start_mu = now_mu()

        times = [0.0] * self.num_points
        voltages = [0.0] * self.num_points

        for i in range(self.num_points):
            self.core.break_realtime()
            t_mu = now_mu()
            t = self.core.mu_to_seconds(t_mu - t_start_mu)
            val = self.suservo.get_adc(self.adc_channel)

            times[i] = t
            voltages[i] = val

        self.set_dataset(DATASET_KEY_T, np.array(times), broadcast=True)
        self.set_dataset(DATASET_KEY_V, np.array(voltages), broadcast=True)

        # Annoying plotting hack
        self.set_dataset(
            DATASET_KEY_V_ERR_HACK, np.array([0.001] * self.num_points), broadcast=True
        )

    @kernel
    def set_all_attenuations(self, attenuation: TFloat):
        """
        Set all channels on the same DDS as this channel to the same, given
        attenuation

        This is annoyingly required because there is no way of getting
        information out from the SUServo gateware about the current settings, so
        they have to be reset on each run.
        """
        logger.warning("Setting the attenuator for all channels")

        self.core.break_realtime()
        cpld = self.suservo_channel.dds.cpld  # type: CPLD
        cpld.get_att_mu()
        attenuation_mu = cpld.att_to_mu(attenuation)
        att_reg = (
            attenuation_mu
            | (attenuation_mu << 1 * 8)
            | (attenuation_mu << 2 * 8)
            | (attenuation_mu << 3 * 8)
        )
        self.core.break_realtime()
        cpld.set_all_att_mu(att_reg)

    @kernel
    def set_this_attenuation(self, attenuation: TFloat):
        # Set the attenuator for this channel on this Urukul
        attenuator_channel = self.suservo_channel.servo_channel % 4
        cpld = self.suservo_channel.dds.cpld  # type: CPLD
        cpld.set_att(attenuator_channel, attenuation)

    @kernel
    def set_dds_params(
        self,
        frequency: TFloat,
        amplitude: TFloat,
        rf_switch_state: TBool,
        setpoint_v: TFloat,
    ):
        # Setpoints are stored in units of full scale, where 1.0 -> +10V, -1.0 -> -10V
        setpoint = -1.0 * setpoint_v / 10.0
        # Configure profile 0 to have the requested amplitude and frequency
        self.suservo_channel.set_y(profile=self.adc_channel, y=amplitude)
        self.suservo_channel.set_dds(
            profile=self.adc_channel,
            offset=setpoint,
            frequency=frequency,
            phase=0.0,
        )

        # Enable profile 0 and the suservo more widely
        self.suservo_channel.set(
            en_out=(1 if rf_switch_state else 0), en_iir=0, profile=self.adc_channel
        )
