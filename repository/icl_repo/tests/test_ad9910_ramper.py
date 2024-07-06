import logging

from artiq.coredevice.ad9910 import _AD9910_REG_CFR2
from artiq.coredevice.ad9910 import _AD9910_REG_RAMP_LIMIT
from artiq.coredevice.ad9910 import _AD9910_REG_RAMP_RATE
from artiq.coredevice.ad9910 import _AD9910_REG_RAMP_STEP
from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import EnumerationValue
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import NumberValue
from artiq.experiment import TFloat
from artiq.experiment import TInt32
from numpy import ceil
from numpy import int32
from numpy import int64


logger = logging.getLogger(__name__)


class AD9910Ramper(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core
        self.setattr_device("urukul8_ch0")
        self.urukul8_ch0: AD9910

        self.dds = self.urukul8_ch0

        self.setattr_argument(
            "f_min", NumberValue(default=10e6, unit="MHz", precision=6)
        )
        self.setattr_argument(
            "f_max", NumberValue(default=20e6, unit="MHz", precision=6)
        )
        self.setattr_argument(
            "df_dt", NumberValue(default=1e6, unit="MHz", precision=6)
        )

        self.setattr_argument(
            "mode", EnumerationValue(["Triangle", "Positive saw", "Negative saw"])
        )

    def prepare(self):
        modes = {
            "Triangle": 0,
            "Positive saw": 1,
            "Negative saw": 2,
        }

        self.scan_type = modes[self.mode]

    @kernel
    def run(self):
        self.core.reset()
        delay(100e-3)

        self.dds.init()

        self.core.break_realtime()
        self.start_ramp(self.df_dt, self.f_min, self.f_max, self.scan_type)

        delay(100e-3)
        rr = self.dds.read32(_AD9910_REG_RAMP_RATE)
        self.core.break_realtime()
        rs = self.dds.read64(_AD9910_REG_RAMP_STEP)

        rs_top = 0xFFFFFFFF & (rs >> 32)
        rs_bottom = 0xFFFFFFFF & rs

        logger.info("Reading back from AD9910:")
        logger.info("Ramp step = 0x%X,0x%X", rs_top, rs_bottom)
        logger.info("Ramp rate = 0x%X", rr)

    @kernel
    def extended_set_cfr2(
        self,
        asf_profile_enable: TInt32 = 1,
        drg_enable: TInt32 = 0,
        effective_ftw: TInt32 = 1,
        sync_validation_disable: TInt32 = 0,
        matched_latency_enable: TInt32 = 0,
        no_dwell_high: TInt32 = 0,
        no_dwell_low: TInt32 = 0,
    ):
        """Set CFR2. See the AD9910 datasheet for parameter meanings.

        This is a copy/paste of the ARTIQ implementation but with control of the NO-DWELL bits added

        This method does not pulse IO_UPDATE.

        :param asf_profile_enable: Enable amplitude scale from single tone profiles.
        :param drg_enable: Digital ramp enable.
        :param no_dwell_high: Set the NO-DWELL high bit.
        :param no_dwell_low: Set the NO-DWELL low bit.
        :param effective_ftw: Read effective FTW.
        :param sync_validation_disable: Disable the SYNC_SMP_ERR pin indicating
            (active high) detection of a synchronization pulse sampling error.
        :param matched_latency_enable: Simultaneous application of amplitude,
            phase, and frequency changes to the DDS arrive at the output

            * matched_latency_enable = 0: in the order listed
            * matched_latency_enable = 1: simultaneously.
        """
        self.dds.write32(
            _AD9910_REG_CFR2,
            (asf_profile_enable << 24)
            | (drg_enable << 19)
            | (no_dwell_high << 18)
            | (no_dwell_low << 17)
            | (effective_ftw << 16)
            | (matched_latency_enable << 7)
            | (sync_validation_disable << 5),
        )

    @kernel
    def set_ramp_parameters_mu(
        self,
        pos_freq_step_mu: TInt32,
        pos_delay_mu: TInt32,
        neg_freq_step_mu: TInt32 = 0,
        neg_delay_mu: TInt32 = 0,
    ):
        """Sets the upwards and downwards DRG ramp step sizes and delays

        By default, set the negative ramp rate to the same as the positive one.

        This function does not enable the DRG.
        """

        if neg_freq_step_mu == 0:
            neg_freq_step_mu = pos_freq_step_mu
        if neg_delay_mu == 0:
            neg_delay_mu = pos_delay_mu

        self.dds.write64(_AD9910_REG_RAMP_STEP, neg_freq_step_mu, pos_freq_step_mu)

        ramp_rate = (pos_delay_mu & 0xFFFF) | (((neg_delay_mu) & 0xFFFF) << 16)
        self.dds.write32(_AD9910_REG_RAMP_RATE, ramp_rate)

    @kernel
    def set_ramp_parameters(self, freq_step: TFloat, delay: TFloat):
        """Sets the upwards and downwards DRG ramp step sizes and delays

        This function does not enable the DRG.
        """
        freq_step_mu = self.dds.frequency_to_ftw(freq_step)
        delay_mu = int32(round(self.dds.sysclk / 4 * delay))

        self.set_ramp_parameters_mu(freq_step_mu, delay_mu)

    @kernel
    def set_ramp_limits_mu(self, frequency_low_mu: TInt32, frequency_high_mu: TInt32):
        """Sets the high and low frequency limits for the DRG

        This function does not enable the DRG.
        """
        self.dds.write64(_AD9910_REG_RAMP_LIMIT, frequency_high_mu, frequency_low_mu)

    @kernel
    def set_ramp_limits(self, frequency_low: TFloat, frequency_high: TFloat):
        """Sets the high and low frequency limits for the DRG

        This function does not enable the DRG.
        """
        self.set_ramp_limits_mu(
            self.dds.frequency_to_ftw(frequency_low),
            self.dds.frequency_to_ftw(frequency_high),
        )

    @kernel
    def start_ramp(
        self, rate: TFloat, freq_low: TFloat, freq_high: TFloat, wave_type: TInt32 = 0
    ):
        """Configures a triangle-wave ramp with the given rate in Hz/s and
        frequency limits.

        This method sets the step size to the smallest possible amount that will
        permit the desired ramp rate then varies the time between steps to get
        the requested rate.

        This function enables the DRG immediately.

        :param rate: Ramp rate in Hz/s
        :param freq_low: Low extent of the ramp in Hz
        :param freq_high: High extent of the ramp in Hz
        :param wave_type: Type of scan. 0 (default) = triangle, 1 = positive-ramping sawtooth, 2 = negative-ramping sawtooth
        """

        factor = (4.0 * (2.0**32.0)) * rate / self.dds.sysclk**2.0

        # Don't allow steps smaller than 1000 LSBs otherwise we'll be very coarse in our frequency setting
        freq_step_mu = int32(max(ceil(factor), 1000.0))
        delay_mu = int32(round(freq_step_mu / factor))

        logger.info("freq_step_mu = %s", freq_step_mu)
        logger.info("delay_mu = %s", delay_mu)
        self.core.break_realtime()

        self.set_ramp_limits(freq_low, freq_high)

        max_step_mu = 0x7FFFFFFF
        min_wait_mu = 1

        if wave_type == 0:
            self.set_ramp_parameters_mu(
                pos_freq_step_mu=freq_step_mu,
                pos_delay_mu=delay_mu,
                neg_freq_step_mu=freq_step_mu,
                neg_delay_mu=delay_mu,
            )
        elif wave_type == 1:
            self.set_ramp_parameters_mu(
                pos_freq_step_mu=freq_step_mu,
                pos_delay_mu=delay_mu,
                neg_freq_step_mu=max_step_mu,
                neg_delay_mu=min_wait_mu,
            )
        elif wave_type == 2:
            self.set_ramp_parameters_mu(
                pos_freq_step_mu=max_step_mu,
                pos_delay_mu=min_wait_mu,
                neg_freq_step_mu=freq_step_mu,
                neg_delay_mu=delay_mu,
            )
        else:
            raise ValueError("wave_type must be 0, 1 or 2")

        self.extended_set_cfr2(drg_enable=1, no_dwell_low=1, no_dwell_high=1)

        # Pulse IO_UPDATE
        self.dds.cpld.io_update.pulse_mu(8)
