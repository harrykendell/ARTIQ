import logging

import numpy as np
from artiq.coredevice.rtio import rtio_input_timestamped_data
from artiq.experiment import *

logger = logging.getLogger(__name__)


class InputTimeout(EnvExperiment):
    def build(self):
        self.setattr_device("core")

        self.setattr_argument(
            "channel", NumberValue(default=0, precision=0, scale=1, step=1)
        )
        self.setattr_argument(
            "timeout", NumberValue(default=1, precision=2, scale=1, unit="s")
        )

    @kernel
    def run(self):
        timeout_mu = self.core.seconds_to_mu(self.timeout)

        logger.info("timeout_mu = %s", timeout_mu)

        self.core.reset()

        # This should timeout since there's no input
        timestamp, data = rtio_input_timestamped_data(
            now_mu() + np.int64(timeout_mu), self.channel
        )

        print(timestamp)
        print(data)
