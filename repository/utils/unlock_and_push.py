import logging

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import EnumerationValue, delay, kernel, ms
from ndscan.experiment import ExpFragment, FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import VDrivenSupply
from repository.utils.get_local_devices import get_local_devices

logger = logging.getLogger(__name__)


class UnlockAndPushExp(ExpFragment):
    """
    Assert an unlock on a laser and push it over then bring it back to its default value after a delay.

    Breaks out the :class:`~SetSupplies` Fragment.
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        lasers = [dev.name for dev in VDrivenSupply.values() if dev.unit == "MHz"]
        default = lasers[0]

        self.setattr_argument("laser", EnumerationValue(lasers, default=default))
        self.laser: str

        if self.laser is not None:
            current_config = VDrivenSupply[self.laser]
        else:
            current_config = VDrivenSupply[default]

        self.setattr_fragment("setter", SetSupplies, [current_config], init=False)
        self.setter: SetSupplies

        self.setattr_param(
            "offset", FloatParam, "Frequency to push by", default=0.0, unit="MHz"
        )
        self.offset: FloatParamHandle

        self.setattr_param(
            "time_to_shift",
            FloatParam,
            "Delay for the laser to move",
            default=5 * ms,
            unit="ms",
        )
        self.time_to_shift: FloatParamHandle

        # NB this means TTLIn cant be used but due to type checking we have no option
        unlocks = [dev for dev in get_local_devices(self, TTLInOut) if "unlock" in dev]
        self.setattr_argument(
            "ttl",
            EnumerationValue(unlocks),
        )
        self.ttl: str

        if self.ttl is not None:
            self.unlock_ttl: TTLInOut = self.get_device(self.ttl)
        else:
            self.unlock_ttl: TTLInOut = self.get_device(unlocks[0])

    @kernel
    def run_once(self):
        self.core.break_realtime()

        """
        Unlock an ECDL
        """
        self.unlock_ttl.on()
        self.setter.set_outputs([self.offset.get()])
        delay(200 * ms)

        """
        Relock an ECDL

        Unpush and then after `time_to_shift` seconds, turn the TTL off
        """
        self.setter.set_to_defaults()
        delay(self.time_to_shift.get())
        self.unlock_ttl.off()
        logging.warning("Relocking %s", self.laser)

        delay(200 * ms)


SetAnalogCurrentSupplyExp = make_fragment_scan_exp(UnlockAndPushExp)
