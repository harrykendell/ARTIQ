import logging
import time
from math import isnan

from artiq.coredevice.core import Core
from artiq.master.scheduler import Scheduler
from ndscan.experiment import *
from ndscan.experiment.parameters import BoolParamHandle
from wand.server import ControlInterface as WANDControlInterface
from wand.tools import WLMMeasurementStatus

from icl_repo.lib import constants
from icl_repo.lib.fragments.set_eom_sidebands import SetEOMSidebandsFrag

logger = logging.getLogger(__name__)

MAX_TIME_TO_FAST_LOCK = 60  # s
MAX_FINAL_OFFSET = 5e6  # Hz
WAND_FAST_LOCK_POLLING = 0.5  # s


class SwitchIsotopeFrag(ExpFragment):
    def build_fragment(self, *args, **kwargs) -> None:
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("scheduler")
        self.scheduler: Scheduler

        self.setattr_fragment("set_sidebands_frag", SetEOMSidebandsFrag)
        self.set_sidebands_frag: SetEOMSidebandsFrag

        self.setattr_param(
            "sr87",
            BoolParam,
            "True = sr87, false = sr88",
            default=False,
        )
        self.sr87: BoolParamHandle
        self.set_sidebands_frag.bind_param("sr87", self.sr87)

        self.setattr_device("wand_server")
        self.wand_server: WANDControlInterface

    def run_once(self) -> None:
        self.set_sidebands()
        self.steer_wand()

    def steer_wand(self):
        if self.sr87.get():
            offsets = constants.WAND_OFFSETS_87
        else:
            offsets = constants.WAND_OFFSETS_88

        for laser, offset in offsets.items():
            if isnan(offset):
                logger.info("Disabling lock for laser %s", laser)
                self.wand_server.unlock(laser=laser, name="")
            else:
                logger.info("Setting laser %s to %.6f MHz", laser, 1e-6 * offset)
                self.wand_server.lock(laser=laser, set_point=offset, timeout=None)

        initial_laser_db = self.wand_server.get_laser_db()

        laser_lock_initial_settings = []
        for laser, offset in offsets.items():
            gain = initial_laser_db[laser]["lock_gain"]
            poll_time = initial_laser_db[laser]["lock_poll_time"]
            capture_range = initial_laser_db[laser]["lock_capture_range"]
            laser_lock_initial_settings.append((laser, gain, poll_time, capture_range))

        logger.info("Setting lock poll time = %.1fs", WAND_FAST_LOCK_POLLING)

        laser_unlocked = {l: not isnan(o) for l, o in offsets.items()}

        try:
            for laser, gain, poll_time, capture_range in laser_lock_initial_settings:
                self.wand_server.set_lock_params(
                    laser=laser,
                    gain=gain,
                    poll_time=WAND_FAST_LOCK_POLLING,
                    capture_range=capture_range,
                )

            t_end = time.time() + MAX_TIME_TO_FAST_LOCK
            while any(laser_unlocked.values()) and time.time() < t_end:
                for laser, unlocked in laser_unlocked.items():
                    self.scheduler.pause()
                    if unlocked:
                        desired_offset = offsets[laser]
                        meas = self.wand_server.get_freq(
                            laser=laser, offset_mode=True, age=1
                        )
                        status, actual_offset, _ = meas
                        if status != WLMMeasurementStatus.OKAY:
                            continue
                        if abs(desired_offset - actual_offset) < MAX_FINAL_OFFSET:
                            logger.info("Laser %s is locked", laser)
                            laser_unlocked[laser] = False

                time.sleep(1)

        finally:
            for laser, gain, poll_time, capture_range in laser_lock_initial_settings:
                self.wand_server.set_lock_params(
                    laser=laser,
                    gain=gain,
                    poll_time=poll_time,
                    capture_range=capture_range,
                )
            logger.info("Lock settings restored")

    @kernel
    def set_sidebands(self):
        self.core.break_realtime()
        self.set_sidebands_frag.set_sidebands()


SwitchIsotope = make_fragment_scan_exp(SwitchIsotopeFrag)
