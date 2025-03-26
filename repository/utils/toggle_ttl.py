from artiq.coredevice.core import Core
from ndscan.experiment import ExpFragment
from artiq.language import delay, ms, parallel
from artiq.language.core import kernel
from ndscan.experiment import make_fragment_scan_exp


class PulserFrag(ExpFragment):
    """
    SHUTTER TESTING: Toggle the 3DMOT shutter and the probe TTL
    """

    def build_fragment(self) -> None:
        self.core: Core = self.get_device("core")

        self.shutter = self.get_device("shutter_3DMOT")
        self.probe = self.get_device("ttl11")

    @kernel
    def run_once(self) -> None:
        self.core.reset()
        self.core.break_realtime()

        for _ in range(50):
            with parallel:
                self.shutter.on()
                self.probe.on()

            delay(20 * ms)

            with parallel:
                self.shutter.off()
                self.probe.off()

            delay(50 * ms)


Pulser = make_fragment_scan_exp(PulserFrag)
