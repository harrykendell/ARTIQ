import logging

from artiq.coredevice.core import Core
from artiq.experiment import EnumerationValue, delay, kernel, A
from ndscan.experiment import ExpFragment, FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle

from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import VDrivenSupply

logger = logging.getLogger(__name__)


class SetAnalogCurrentSupplyExp(ExpFragment):
    """
    Set the current for an analog current supply

    Breaks out the :class:`~SetSupplies` Fragment.
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        default = VDrivenSupply.keys()[0]
        self.setattr_argument(
            "current_supply", EnumerationValue(VDrivenSupply.keys(), default=default)
        )
        self.current_supply: str

        if self.current_supply is not None:
            current_config = VDrivenSupply[self.current_supply]
        else:
            current_config = VDrivenSupply[default]

        self.setattr_fragment("setter", SetSupplies, [current_config], init=False)
        self.setter: SetSupplies

        self.setattr_param(
            "current", FloatParam, "Current to set", default=0.0, unit="A"
        )
        self.current: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.break_realtime()
        delay(10e-3)
        self.setter.set_outputs([self.current.get() * A])


SetAnalogCurrentSupplyExp = make_fragment_scan_exp(SetAnalogCurrentSupplyExp)
