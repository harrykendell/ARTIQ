import logging
import time
from typing import List
from typing import Optional
from typing import Tuple

from artiq.coredevice.ad9910 import AD9910
from artiq.coredevice.core import Core
from artiq.experiment import kernel
from artiq.experiment import portable
from artiq.experiment import TFloat
from artiq.experiment import TList
from artiq.master.scheduler import Scheduler
from artiq_influx_generic import InfluxController
from koheron_ctl200_laser_driver import CTL200
from ndscan.experiment import ExpFragment
from ndscan.experiment import Fragment
from ndscan.experiment import LinearGenerator
from ndscan.experiment import setattr_subscan
from ndscan.experiment import Subscan
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import BoolParam
from ndscan.experiment.parameters import BoolParamHandle
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle
from ndscan.experiment.parameters import IntParam
from ndscan.experiment.parameters import IntParamHandle

import icl_repo.lib.constants as constants
from icl_repo.injected_diodes.scan_koheron_current import ScanKoheronCurrentFrag

logger = logging.getLogger(__name__)


class RelockIJDFrag(ExpFragment):
    """
    Relock one injected diode
    """

    def build_fragment(
        self, controller_name: Optional[str] = None, *args, **kwargs
    ) -> None:
        self.setattr_param(
            "v_increase_threshold",
            FloatParam,
            "Increase from minimum voltage that defines the upper end of the injection window",
            default=0.01,
            unit="mV",
        )
        self.v_increase_threshold: FloatParamHandle

        self.setattr_param(
            "i_jump_above_window",
            FloatParam,
            "How far above the window to jump when relocking",
            default=3 * 1e-3,
            unit="mA",
        )
        self.i_jump_above_window: FloatParamHandle

        self.setattr_param(
            "t_relock_waittime",
            FloatParam,
            "How long to wait after initial jump when relocking",
            unit="ms",
            default=1000,
        )
        self.t_relock_waittime: FloatParamHandle

        self.setattr_param(
            "i_start_scan",
            FloatParam,
            "Current to start scan",
            unit="mA",
            default=340 * 1e-3,
        )
        self.i_start_scan: FloatParamHandle

        self.setattr_param(
            "i_end_scan",
            FloatParam,
            "Current to end scan",
            unit="mA",
            default=320 * 1e-3,
        )
        self.i_end_scan: FloatParamHandle

        self.setattr_param(
            "num_points",
            IntParam,
            "Number of scan points",
            default=100,
        )
        self.num_points: IntParamHandle

        self.setattr_param(
            "frac_through_window",
            FloatParam,
            "Fraction of the way through the window to lock at",
            default=0.75,
            min=0,
            max=1,
        )
        self.frac_through_window: IntParamHandle

        self.setattr_fragment(
            "frag_ijd_scanner", ScanKoheronCurrentFrag, controller_name=controller_name
        )
        self.frag_ijd_scanner: ScanKoheronCurrentFrag

        # Disable AOM setting by the scanner - we'll handle it here
        self.frag_ijd_scanner.override_param("change_aom", False)

        setattr_subscan(
            self,
            "scan_ijd_current",
            self.frag_ijd_scanner,
            [(self.frag_ijd_scanner, "current")],
        )
        self.scan_ijd_current: Subscan

        self.setattr_device("influx_logger")
        self.influx_logger: InfluxController

        self.setattr_device("scheduler")
        self.scheduler: Scheduler

        self.setattr_device("core")
        self.core: Core

        self.controller_name = controller_name

        if self.controller_name in constants.AD9910_BEAMS:
            urukul_channel_name, freq, att = constants.AD9910_BEAMS[
                self.controller_name
            ]

            self.urukul_channel: AD9910 = self.get_device(urukul_channel_name)
            self.urukul_channel_name = urukul_channel_name
            self.aom_freq, self.aom_attenuation = freq, att

    def host_setup(self):
        super().host_setup()

        # Request the ijd controller device
        self.ijd_controller: CTL200 = self.frag_ijd_scanner.controller

    def run_once(self) -> None:
        self.relock()

    @kernel
    def set_aom(self, freq: TFloat, att: TFloat):
        self.core.break_realtime()
        self.urukul_channel.init()
        self.urukul_channel.set(frequency=freq, amplitude=1.0)
        self.urukul_channel.set_att(att)
        self.urukul_channel.sw.on()

    def relock(self) -> None:
        # Set AOM if required
        if hasattr(self, "urukul_channel"):
            logger.info(
                "Setting AOM %s to %.0f MHz, %.1f dB",
                self.urukul_channel_name,
                1e-6 * self.aom_freq,
                self.aom_attenuation,
            )
            self.set_aom(self.aom_freq, self.aom_attenuation)

        # scan over a range of currents on the IJD
        coordinates, values, analysis_results = self.scan_ijd_current.run(  # type: ignore
            [
                (
                    self.frag_ijd_scanner.current,
                    LinearGenerator(
                        self.i_start_scan.get(),
                        self.i_end_scan.get(),
                        self.num_points.get(),
                        False,
                    ),
                )
            ]
        )
        logger.debug("coordinates")
        logger.debug(coordinates)
        logger.debug("values")
        logger.debug(values)
        logger.debug("analysis_results")
        logger.debug(analysis_results)

        currents = coordinates[self.frag_ijd_scanner.current]
        logger.debug("currents")
        logger.debug(currents)

        voltages = values[self.frag_ijd_scanner.voltage]
        logger.debug("voltages")
        logger.debug(voltages)

        # Find the optimum current
        lock_point, window_start, window_end, v_window_start = self.find_lock_point(currents, voltages)  # type: ignore
        start_point = lock_point + self.i_jump_above_window.get()
        t_wait = self.t_relock_waittime.get()

        # Jump to it
        logger.debug("Prelock - Setting I = %.2f mA", start_point * 1e3)
        self.ijd_controller.set_current_mA(start_point * 1e3)  # type: ignore

        logger.debug("Sleeping for %.3f s", t_wait)
        time.sleep(t_wait)

        logger.info("Lock - Setting I = %.2f mA", lock_point * 1e3)
        self.ijd_controller.set_current_mA(lock_point * 1e3)  # type: ignore

        # Log action
        self.influx_logger.write(
            tags={
                "type": self.__class__.__name__,
                "controller": self.controller_name,
                "rid": self.scheduler.rid,
            },
            fields={
                "i_lock": lock_point,
                "i_start": window_start,
                "i_end": window_end,
                "i_window_size": window_end - window_start,
                "v_window": v_window_start,
            },
        )

    @portable
    def find_lock_point(
        self, current: TList, voltage: TList
    ) -> Tuple[float, float, float, float]:
        """
        Datapoints should be in descending order of current
        """

        # Find start of the window (low current end):
        biggest_diff = 0
        ind_biggest_diff = 0
        for i in range(len(current) - 1):  # type: ignore
            diff = voltage[i + 1] - voltage[i]
            if diff > biggest_diff:
                biggest_diff = diff
                ind_biggest_diff = i

        window_start = current[ind_biggest_diff]

        # Find end of window (i.e point before the voltage raises by v_increase_threshold)
        v_window_start = voltage[ind_biggest_diff]
        v_threshold = v_window_start + self.v_increase_threshold.get()
        window_end = current[0]
        for i in range(ind_biggest_diff, 0, -1):
            if voltage[i] > v_threshold:
                window_end = current[i + 1]
                break

        logger.debug("window_start=%.3f, window_end=%.3f", window_start, window_end)

        return (
            window_start + (window_end - window_start) * self.frac_through_window.get(),
            window_start,
            window_end,
            v_window_start,
        )


class RelockAllIJDsFrag(ExpFragment):
    """
    Relock all IJDs
    """

    def build_fragment(self) -> None:
        ijd_controller_names = [
            "blue_IJD1_controller",
            "blue_IJD2_controller",
            "blue_IJD3_controller",
            "red_IJD1_controller",
        ]

        self.ijd_controller_frags: List[RelockIJDFrag] = []
        self.ijd_controller_enabled: List[BoolParamHandle] = []

        # Request a relock fragment for each IJD controller

        for ijd_controller_name in ijd_controller_names:
            fragment_name = f"frag_relocker_{ijd_controller_name}"

            frag = self.setattr_fragment(
                fragment_name,
                RelockIJDFrag,
                ijd_controller_name,
            )

            self.ijd_controller_enabled.append(
                self.setattr_param(
                    f"{ijd_controller_name}_enabled",
                    BoolParam,
                    description=f"{ijd_controller_name} enabled",
                    default=True,
                )
            )

            self.ijd_controller_frags.append(frag)  # type: ignore

        # Create top-level parameters which will override the
        # subfragment's parameters
        self.setattr_param_like("num_points", self.ijd_controller_frags[0], default=100)
        self.setattr_param_like(
            "current_waittime",
            self.ijd_controller_frags[0].frag_ijd_scanner,
            default=5e-3,
        )
        self.num_points: FloatParamHandle
        self.current_waittime: FloatParamHandle

        # For each subfragment relocked, rebind parameters to set defaults for
        # each IJD
        for frag, ijd_controller_name in zip(
            self.ijd_controller_frags, ijd_controller_names
        ):
            settings = constants.IJD_DEFAULTS[ijd_controller_name]

            frag.bind_param("num_points", self.num_points)

            self.setattr_param_rebind(
                f"{ijd_controller_name}_start_current",
                frag,
                original_name="i_start_scan",
                default=settings.window_high,
            )

            self.setattr_param_rebind(
                f"{ijd_controller_name}_end_current",
                frag,
                original_name="i_end_scan",
                default=settings.window_low,
            )

            self.setattr_param_rebind(
                f"{ijd_controller_name}_temperature",
                frag.frag_ijd_scanner,
                original_name="temperature",
                default=settings.temperature,
            )

            self.setattr_param_rebind(
                f"{ijd_controller_name}_t_relock_waittime",
                frag,
                original_name="t_relock_waittime",
                default=settings.relock_waittime,
            )

            self.setattr_param_rebind(
                f"{ijd_controller_name}_i_jump_above_window",
                frag,
                original_name="i_jump_above_window",
                default=settings.relock_step,
            )

            # Disable waiting for temperature to settle - the relock algorithm
            # will just have to be run again if it fails because of temperature
            # and we don't want to delay the other IJDs
            frag.frag_ijd_scanner.override_param("temperature_waittime", 0)

        self.frag_relocker_blue_IJD1_controller: RelockIJDFrag

    def run_once(self) -> None:
        # Relock each IJD in order
        for i in range(len(self.ijd_controller_frags)):
            ijd_relock_frag = self.ijd_controller_frags[i]
            enabled = self.ijd_controller_enabled[i]

            if enabled.get():
                ijd_relock_frag.relock()


RelockSingleIJD = make_fragment_scan_exp(RelockIJDFrag)
RelockAllIJDs = make_fragment_scan_exp(RelockAllIJDsFrag)
