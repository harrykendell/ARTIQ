import logging
import random
import time

import requests
from artiq.experiment import *

logger = logging.getLogger(__name__)

# List of tasmota sockets to toggle. They will be turned off and then turned on
# in this order
TASMOTA_HOSTS = [
    "tasmota-artiq-master",
    "tasmota-artiq-red",
    "tasmota-artiq-blue",
    "tasmota-artiq-plantroom",
]

POWER_ON_CMD = "http://{}/cm?cmnd=Power%20on"
POWER_OFF_CMD = "http://{}/cm?cmnd=Power%20off"

DATASET_NAME = "toggle_code"


class HardRebootARTIQCrates(EnvExperiment):
    "Hard reboot the artiq crates by power cycling them"

    def build(self):
        self.setattr_argument(
            "confirmation_code",
            NumberValue(default=-1, precision=0, scale=1, step=1, min=0, type="int"),
        )
        self.confirmation_code: int

    def run(self):
        if not self.is_user_sure():
            return

        logger.warning("Rebooting ARTIQ crates now")
        self.toggle_crates()

    def toggle_crates(self):
        for host in TASMOTA_HOSTS:
            logger.info("Turning off %s", host)
            requests.get(POWER_OFF_CMD.format(host))

        time.sleep(3)

        for host in TASMOTA_HOSTS:
            logger.info("Turning on %s", host)
            requests.get(POWER_ON_CMD.format(host))

    def is_user_sure(self):
        """
        Ensure the user is certain by getting them to write a 3 digit code as an
        argument
        """
        target_code = self.get_dataset(DATASET_NAME, default=0, archive=False)
        new_code = random.randint(100, 999)

        # Save a new target code to a dataset
        self.set_dataset(
            DATASET_NAME, new_code, archive=True, broadcast=True, persist=False
        )

        # Check if the right code was passed
        if self.confirmation_code == target_code:
            return True
        else:
            logger.warning(
                "Are you sure you want to power cycle the crates? "
                "If so, enter the code %d and run this experiment again",
                new_code,
            )
            return False
