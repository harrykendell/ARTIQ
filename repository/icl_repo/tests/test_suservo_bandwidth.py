"""
See https://github.com/m-labs/artiq/issues/1338#issuecomment-512031821
"""
import math
from functools import reduce

import numpy as np
from artiq.coredevice.suservo import SUServo
from artiq.experiment import *


class DetermineServoPeriod(EnvExperiment):
    """Determine servo period

    This determines the length of a cycle on the given SUServo device by
    repeatedly fetching the status word and recording timestamps where the
    "done" bit is set (which is strobed for one clock cycle at the end of
    each cycle).
    """

    def build(self):
        self.servo_name = self.get_argument(
            "Servo device name",
            StringValue(default="suservo0"),
        )

        self.num_dones = self.get_argument(
            "Number of 'done' observations",
            NumberValue(default=1000, min=2, step=1, precision=0),
        )

        self.setattr_device("core")

    def run(self):
        self.acquire(self.get_device(self.servo_name), self.num_dones)

    @kernel
    def acquire(self, servo, num_dones):
        # type:(SUServo, int) -> None
        timestamps = [np.int64(0)] * num_dones

        self.core.break_realtime()
        servo.set_config(enable=1)
        delay(10 * us)

        i = 0
        while i < num_dones:
            self.core.break_realtime()
            if servo.get_status() & 0x2:
                timestamps[i] = now_mu()
                i += 1

        self.post_results(timestamps)

    def post_results(self, timestamps):
        timestamps = np.array(timestamps)
        deltas = timestamps[1:] - timestamps[:-1]

        cycle_mu = reduce(lambda a, b: math.gcd(a, b), deltas, deltas[0])
        print(
            "Cycle length (or multiple thereof):",
            self.core.mu_to_seconds(cycle_mu),
            "s",
        )
