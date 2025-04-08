import logging

from artiq.coredevice.core import Core
from artiq.experiment import EnumerationValue, delay, kernel
from artiq.language.units import ms
from ndscan.experiment import ExpFragment, FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle

from repository.fragments.eom_setter import SetEOM
from repository.models.devices import Eom

logger = logging.getLogger(__name__)


class PulseEOMExpFrag(ExpFragment):
    """
    Continually pulse the EOM

    Breaks out the :class:`~SetEOM` Fragment.
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        default = Eom.keys()[0]
        self.setattr_argument("eom", EnumerationValue(Eom.keys(), default=default))
        self.eom: str

        if self.eom is not None:
            config = Eom[self.eom]
        else:
            config = Eom[default]

        self.setattr_fragment("setter", SetEOM, config, init=False)
        self.setter: SetEOM

        self.setattr_param(
            "time_on",
            FloatParam,
            "Time to keep the EOM on",
            default=10.0 * ms,
            unit="ms",
        )
        self.time_on: FloatParamHandle

        self.setattr_param(
            "time_off",
            FloatParam,
            "Time to keep the EOM off",
            default=1.0 * ms,
            unit="ms",
        )
        self.time_off: FloatParamHandle

        # Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "setter",
            "time_on",
            "time_off",
        }

    @kernel
    def run_once(self):
        self.core.break_realtime()

        while True:
            self.setter.pulse(self.time_on.get(), self.time_off.get())

    @kernel
    def device_cleanup(self):
        self.setter.enable()
        self.device_cleanup_subfragments()


PulseEOMExp = make_fragment_scan_exp(PulseEOMExpFrag)
