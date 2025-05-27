from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import EnvExperiment, NumberValue
from artiq.language import delay, kernel, now_mu, parallel
from artiq.language.units import ms, s
from ndscan.experiment import (
    ExpFragment,
    FloatParam,
    IntParam,
    OnlineFit,
    make_fragment_scan_exp,
)


class ElapsedTimer(ExpFragment):
    """
    Ramp testing NDSCAN

    Trying to work out what the hell is going on with the elapsed time
    We lose all of our slack if we submit more than some number of pulses

    1 TTL: 65
    2 TTLs: 257
    3 TTLs: 129
    4 TTLs: 129
    5 TTLs: 65
    6 TTLs: 86
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.ttl3: TTLInOut = self.get_device("ttl3")
        self.ttl5: TTLInOut = self.get_device("ttl5")
        self.ttl6: TTLInOut = self.get_device("ttl6")
        self.ttl7: TTLInOut = self.get_device("ttl7")
        self.ttl9: TTLInOut = self.get_device("ttl9")
        self.ttl10: TTLInOut = self.get_device("ttl10")
        self.ttl11: TTLInOut = self.get_device("ttl11")

        self.setattr_result("clock_time")

        self.setattr_param("num_pulses", IntParam, "num_pulses", 1000)
        self.num_pulses: IntParam

    @kernel
    def run_once(self):
        self.core.break_realtime()
        delay(1 * s)

        start_rtio = self.core.get_rtio_counter_mu()
        start_slack = now_mu() - start_rtio

        for _ in range(self.num_pulses.get()):
            with parallel:
                self.ttl3.pulse(duration=0.1 * ms)
                # self.ttl5.pulse(duration=0.1 * ms)
                # self.ttl6.pulse(duration=0.1 * ms)
                # self.ttl7.pulse(duration=0.1 * ms)
                # self.ttl9.pulse(duration=0.1 * ms)
                # self.ttl10.pulse(duration=0.1 * ms)
                # self.ttl11.pulse(duration=0.1 * ms)
            delay(0.1 * ms)

        end_rtio = self.core.get_rtio_counter_mu()
        end_slack = now_mu() - end_rtio

        print(
            "NDSCAN ELAPSED TIMER:",
            self.num_pulses.get(),
            "\nelapsed counter time",
            self.core.mu_to_seconds(end_rtio - start_rtio) * 1000,
            "ms\nelapsed slack time",
            self.core.mu_to_seconds(end_slack - start_slack) * 1000,
            "ms\nstart slack",
            self.core.mu_to_seconds(start_slack) * 1000,
            "ms\nend slack",
            self.core.mu_to_seconds(end_slack) * 1000,
            "ms",
        )

        self.clock_time.push(self.core.mu_to_seconds(end_rtio - start_rtio))

    def get_default_analyses(self):
        return [
            OnlineFit(
                "line",
                data={
                    "x": self.num_pulses,
                    "y": self.clock_time,
                },
            ),
        ]


ScanElapsedTime = make_fragment_scan_exp(ElapsedTimer)


class ElapsedTimer(EnvExperiment):
    """
    Ramp testing

    Trying to work out what the hell is going on with the elapsed time for a train of pulses
    """

    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.ttl10: TTLInOut = self.get_device("ttl10")
        self.ttl11: TTLInOut = self.get_device("ttl11")
        self.ttl9: TTLInOut = self.get_device("ttl9")
        self.ttl3: TTLInOut = self.get_device("ttl3")

        self.setattr_argument(
            "num_pulses",
            NumberValue(
                default=1000,
                precision=0,
                scale=1,
                step=1,
                min=1,
                max=10000,
                type="int",
            ),
            tooltip="Number of pulses to send",
        )

    @kernel
    def run(self):
        self.core.reset()
        delay(1 * s)

        start_rtio = self.core.get_rtio_counter_mu()
        start_slack = now_mu() - start_rtio

        for _ in range(self.num_pulses):
            with parallel:
                self.ttl3.pulse(duration=0.1 * ms)
                # self.ttl9.pulse(duration=0.1 * ms)
                # self.ttl10.pulse(duration=0.1 * ms)
                # self.ttl11.pulse(duration=0.1 * ms)
            delay(0.1 * ms)

        end_rtio = self.core.get_rtio_counter_mu()
        end_slack = now_mu() - end_rtio

        print(
            "ELAPSED TIMER:",
            self.num_pulses,
            "\nelapsed counter time",
            self.core.mu_to_seconds(end_rtio - start_rtio) * 1000,
            "ms\nelapsed slack time",
            self.core.mu_to_seconds(end_slack - start_slack) * 1000,
            "ms\nstart slack",
            self.core.mu_to_seconds(start_slack) * 1000,
            "ms\nend slack",
            self.core.mu_to_seconds(end_slack) * 1000,
            "ms",
        )
