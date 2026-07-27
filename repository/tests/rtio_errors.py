from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import EnvExperiment, kernel
from artiq.language.core import at_mu, delay, delay_mu, now_mu
from artiq.language.environment import EnumerationValue
from artiq.language.units import ms


class RTIOErrorTest(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        # Replace this with a harmless, preferably disconnected TTL output.
        self.probe: TTLInOut = self.get_device("probe")

        self.setattr_argument("test", EnumerationValue(["collision", "underflow"]))

    def run(self):
        if self.test == "collision":
            self.test_collision()
        else:
            self.generate_underflow()

    @kernel
    def test_collision(self):
        self.core.reset()

        # Add plenty of positive slack.
        delay(1 * ms)

        coarse_mu = self.core.ref_multiplier

        # Align the first event exactly to a coarse RTIO clock boundary.
        t = now_mu()
        t -= t % coarse_mu

        # Two events on the same channel, with different fine timestamps
        # but within the same coarse RTIO clock cycle.
        at_mu(t)
        self.probe.on()

        delay_mu(1)
        self.probe.off()  # Deliberate RTIO collision; normally discarded.

        # The failed off() may leave the output high. Schedule an unambiguous
        # cleanup event several coarse cycles later.
        at_mu(t + 2 * coarse_mu)
        self.probe.off()

        # Ensure the scheduled events have actually passed before returning.
        self.core.wait_until_mu(now_mu())

    @kernel
    def generate_underflow(self):
        # get_rtio_counter_mu() is already a lower bound on the live wall
        # clock. Move the cursor an additional 1000 mu into the past.
        at_mu(self.core.get_rtio_counter_mu() - 1000)

        # An output event cannot be submitted retrospectively.
        self.probe.on()
