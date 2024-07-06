import logging
import time
from tokenize import String

import artiq
from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import ms
from artiq.experiment import now_mu
from artiq.experiment import NumberValue
from artiq.experiment import rpc
from artiq.experiment import StringValue

logger = logging.getLogger(__name__)


class ToggleTTL(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_argument("ttl_device", StringValue())

    def run(self):
        self.ttl = self.get_device(self.ttl_device)

        self.toggle()

        print("Toggling completed")

    @kernel
    def toggle(self):
        self.core.reset()
        for _ in range(20):
            self.ttl.on()
            delay(1.0)
            self.ttl.off()
            delay(1.0)

        self.core.wait_until_mu(now_mu())
