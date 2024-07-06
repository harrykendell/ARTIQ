import logging
import time
from tokenize import String

import artiq
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import ms
from artiq.experiment import NumberValue
from artiq.experiment import rpc
from artiq.experiment import StringValue

logger = logging.getLogger(__name__)


class Tester(EnvExperiment):
    """Say hello"""

    def build(self):
        self.setattr_device("core")

        self.setattr_argument("message", StringValue())

    def run(self):
        logger.debug(
            "This is a DEBUG message - you'll only see this level of detail if you select DEBUG as your logging level."
        )

        logger.info(
            "Hello world! I'm an experiment running on ARTIQ version %s",
            artiq.__version__,
        )

        logger.warning(
            "This is a WARNING level message, visible for all log levels below WARNING."
        )

        logger.error(
            "This is an ERROR level message - these will almost always be visible"
        )

        logger.critical("This is a CRITICAL message - these cannot be hidden")

        self.say_hello()

    @kernel
    def say_hello(self):
        print(
            """
This is a message from the core itself. Seeing this confirms that core communications
are working correctly. These are much more limited than the logging facilities available in plain python.

However, you still do have access to the logging library, like so
            """
        )

        self.say_hello_from_host()

        logger.info('My message is "%s"', self.message)
        logger.warning('Or it could be a warning, like this: "%s"', self.message)

    @rpc(flags={"asyncccc"})
    def say_hello_from_host(self):
        print(f"I'm running on the host so I can do complex things like 1+1 = {1+1}")
        time.sleep(2)
        print("done")
