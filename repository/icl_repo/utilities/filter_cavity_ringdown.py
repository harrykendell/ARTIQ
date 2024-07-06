import logging
from datetime import datetime
from datetime import timedelta

import artiq
from artiq.coredevice.ad9912 import AD9912
from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import at_mu
from artiq.experiment import delay
from artiq.experiment import EnvExperiment
from artiq.experiment import kernel
from artiq.experiment import ms
from artiq.experiment import now_mu
from artiq.experiment import NumberValue
from artiq.experiment import StringValue

logger = logging.getLogger(__name__)


class TTLRingdown(EnvExperiment):
    """Monitor a TTL line and turn off an Urukul channel, then take data"""

    def build(self):
        self.setattr_device("core")

        self.setattr_argument(
            "frequency",
            NumberValue(default=20e6, unit="MHz", step=0.1e6, precision=1, min=0),
        )
        self.setattr_argument(
            "attenuation",
            NumberValue(default=0, unit="dB", step=0.1, precision=1, min=0),
        )
        self.setattr_argument(
            "runtime",
            NumberValue(default=60, unit="s", step=1, precision=0, min=1, type="float"),
        )
        self.setattr_argument(
            "response_time",
            NumberValue(
                default=10e-6, unit="us", step=0.1e-6, precision=1, min=0, type="float"
            ),
        )

        self.dds = self.get_device("urukul_aom_singlepass_transfer_cavity")
        self.ttl = self.get_device("ttl_transfer_cavity_trigger")

        self.core: Core
        self.dds: AD9912
        self.ttl: TTLInOut

    def run(self):
        end_time = datetime.now() + timedelta(seconds=self.runtime)
        logger.info("Running cavity ringdown measurement until %s", end_time)

        # Convert the response time to machine units
        self.response_time_mu = self.core.seconds_to_mu(self.response_time)

        # Pre-calculate log level
        self.print_debug_statements = logger.isEnabledFor(logging.DEBUG)

        self.watch_dds_for_ttl()

    @kernel
    def watch_dds_for_ttl(self):
        # Calculate the end timestamp
        end_timestamp_mu = self.core.get_rtio_counter_mu() + self.core.seconds_to_mu(
            self.runtime
        )

        self.core.reset()

        # Initialise the DDS
        self.dds.init()
        self.dds.set(self.frequency, 0.0)
        self.dds.set_att(self.attenuation)

        # Read the current value of the ttl
        self.ttl.input()
        delay(1 * ms)
        ttl_state = not bool(self.ttl.sample_get_nonrt())

        if self.print_debug_statements:
            logger.info(
                "Starting experiment with ttl_state = %d", 1 if ttl_state else 0
            )
            self.core.break_realtime()

        # If the ttl is high, turn on the dds. Otherwise turn it off
        self.dds.cfg_sw(ttl_state)

        # Now gate the input for rising or falling edges until the timeout
        end_timestamp_mu = self.ttl.gate_both(self.runtime)

        # For the rest of this Experiment, keep the RF switch in sync with the ttl
        while True:
            ttl_state = not ttl_state

            transition_timestamp_mu = self.ttl.timestamp_mu(end_timestamp_mu)

            if transition_timestamp_mu == -1:
                break
            else:
                at_mu(transition_timestamp_mu + self.response_time_mu)

                if self.print_debug_statements:
                    logger.info(
                        "Received TTL toggle at t_mu = %d", transition_timestamp_mu
                    )
                    logger.info("Switching to RF state = %d", 1 if ttl_state else 0)
                    self.core.break_realtime()

                self.dds.cfg_sw(ttl_state)
