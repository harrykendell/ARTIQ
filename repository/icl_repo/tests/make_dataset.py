import logging
from datetime import datetime

from artiq.experiment import EnvExperiment

logger = logging.getLogger(__name__)


class DataWriter(EnvExperiment):
    """Make some data"""

    def build(self):
        pass

    def run(self):
        self.set_dataset(
            "my_local_data",
            f"{datetime.utcnow()}  This is local data. It stays on the core and never reaches the PC. I ran at {datetime.utcnow()}",
        )
        self.set_dataset(
            "my_broadcast_data",
            f"{datetime.utcnow()}  This is broadcast data - it is sent to the PC and archived, but will not be reloaded on artiq_master restarts",
            broadcast=True,
        )

        self.set_dataset(
            "my_persistent_data",
            f"{datetime.utcnow()}  This is persistent data - it is sent to the PC, archived and will be available after artiq_master restarts",
            persist=True,
        )
