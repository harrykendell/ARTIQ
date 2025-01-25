import logging

from artiq.coredevice.core import Core
from artiq.experiment import EnumerationValue
from artiq.experiment import delay
from artiq.experiment import kernel
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle

from repository.models import VDrivenSupply
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.models.devices import VDRIVEN_SUPPLIES

logger = logging.getLogger(__name__)


class SetAnalogCurrentSupplyExp(ExpFragment):
    """
    Set the current for an analog current supply

    Breaks out the :class:`~SetAnalogCurrentSupplies` Fragment.
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_argument(
            "current_supply",
            EnumerationValue(
                list(VDRIVEN_SUPPLIES.keys()), default=list(VDRIVEN_SUPPLIES.keys())[0]
            ),
        )
        self.current_supply: str

        if self.current_supply is not None:
            current_config = VDRIVEN_SUPPLIES[self.current_supply]

        else:
            current_config = list(VDRIVEN_SUPPLIES.values())[0]

        self.setattr_fragment("setter", SetAnalogCurrentSupplies, [current_config])
        self.setter: SetAnalogCurrentSupplies

        self.setattr_param(
            "current", FloatParam, "Current to set", default=0.0, unit="A"
        )
        self.current: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.break_realtime()
        delay(10e-3)
        self.setter.set_currents([self.current.get()])


SetAnalogCurrentSupplyExp = make_fragment_scan_exp(SetAnalogCurrentSupplyExp)
