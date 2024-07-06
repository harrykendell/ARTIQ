import logging

import numpy as np
from artiq.experiment import EnvExperiment
from artiq.experiment import NumberValue
from artiq_influx_generic import InfluxController

logger = logging.getLogger(__name__)


class WriteToInflux(EnvExperiment):
    """Write to influx"""

    def build(self):
        self.setattr_device("core")

        self.setattr_argument(
            "length_of_dataset", NumberValue(precision=0, min=1, scale=1, step=1)
        )

        self.setattr_device("influx_logger")

    def run(self):
        self.influx_logger: InfluxController

        test_data = np.random.random(self.length_of_dataset)

        logger.info(f"Writing {len(test_data)} entries to the database")

        for x in test_data:
            self.influx_logger.write(fields={"value": x}, tags={"type": "testdata"})

        logger.info("Write completed")
