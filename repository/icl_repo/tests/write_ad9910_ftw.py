import logging
from typing import *

from artiq.coredevice.ad9910 import _AD9910_REG_PROFILE0
from artiq.coredevice.ad9910 import _PHASE_MODE_DEFAULT
from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.ad9910 import DEFAULT_PROFILE
from artiq.coredevice.ad9910 import PHASE_MODE_ABSOLUTE
from artiq.coredevice.ad9910 import PHASE_MODE_CONTINUOUS
from artiq.coredevice.ad9910 import PHASE_MODE_TRACKING
from artiq.coredevice.core import Core
from artiq.coredevice.urukul import CPLD
from artiq.experiment import *
from artiq.experiment import at_mu
from artiq.experiment import delay
from artiq.experiment import delay_mu
from artiq.experiment import now_mu
from numpy import int64
from utils.get_local_devices import get_local_devices


logger = logging.getLogger(__name__)


class WriteAD9910FTW(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        ad9910_devices = get_local_devices(self, AD9910)

        self.setattr_argument("dds_name", EnumerationValue(ad9910_devices))

        self.dds: AD9910 = self.get_device(self.dds_name)

        self.setattr_argument("freq", NumberValue(default=10e6, unit="MHz"))

    @kernel
    def run(self):
        t_one_cycle_mu = int64(self.core.ref_multiplier)

        self.core.reset()

        logger.warning(
            "Setting frequency to %.1f MHz",
            self.freq * 1e6,
        )

        self.core.break_realtime()
        delay(10e-3)

        self.dds.set_frequency(self.freq)

        # We do this in a separate loop so that the IO_updates are
        # almost simultaneous. If we were willing to consume all the
        # RTIO lanes, they could be truely simultaneous
        at_mu(now_mu() & ~7)
        delay_mu(int64(self.dds.sync_data.io_update_delay))
        self.dds.cpld.io_update.pulse_mu(8)  # assumes 8 mu > t_SYN_CCLK
        at_mu(now_mu() & ~7)  # clear fine TSC again

    @kernel
    def set_mu(
        self,
        dds,
        ftw: TInt32 = 0,
        pow_: TInt32 = 0,
        asf: TInt32 = 0x3FFF,
        phase_mode: TInt32 = _PHASE_MODE_DEFAULT,
        ref_time_mu: TInt64 = int64(-1),
        profile: TInt32 = DEFAULT_PROFILE,
        ram_destination: TInt32 = -1,
    ) -> TInt32:
        """Set DDS data in machine units.

        This uses machine units (FTW, POW, ASF). The frequency tuning word
        width is 32, the phase offset word width is 16, and the amplitude
        scale factor width is 14.

        After the SPI transfer, the shared IO update pin is pulsed to
        activate the data.

        .. seealso: :meth:`set_phase_mode` for a definition of the different
            phase modes.

        :param ftw: Frequency tuning word: 32 bit.
        :param pow_: Phase tuning word: 16 bit unsigned.
        :param asf: Amplitude scale factor: 14 bit unsigned.
        :param phase_mode: If specified, overrides the default phase mode set
            by :meth:`set_phase_mode` for this call.
        :param ref_time_mu: Fiducial time used to compute absolute or tracking
            phase updates. In machine units as obtained by `now_mu()`.
        :param profile: Single tone profile number to set (0-7, default: 7).
            Ineffective if `ram_destination` is specified.
        :param ram_destination: RAM destination (:const:`RAM_DEST_FTW`,
            :const:`RAM_DEST_POW`, :const:`RAM_DEST_ASF`,
            :const:`RAM_DEST_POWASF`). If specified, write free DDS parameters
            to the ASF/FTW/POW registers instead of to the single tone profile
            register (default behaviour, see `profile`).
        :return: Resulting phase offset word after application of phase
            tracking offset. When using :const:`PHASE_MODE_CONTINUOUS` in
            subsequent calls, use this value as the "current" phase.
        """
        # Align to coarse RTIO which aligns SYNC_CLK. I.e. clear fine TSC
        # This will not cause a collision or sequence error.
        at_mu(now_mu() & ~7)

        dds.write64(_AD9910_REG_PROFILE0 + profile, (asf << 16) | (pow_ & 0xFFFF), ftw)

        delay_mu(int64(dds.sync_data.io_update_delay))
        dds.cpld.io_update.pulse_mu(8)  # assumes 8 mu > t_SYN_CCLK
        at_mu(now_mu() & ~7)  # clear fine TSC again
        if phase_mode != PHASE_MODE_CONTINUOUS:
            dds.set_cfr1()
            # future IO_UPDATE will activate
        return pow_
