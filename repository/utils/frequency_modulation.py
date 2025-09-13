#import logging
import math

# from artiq.experiment import *
from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import EnumerationValue, delay, kernel
from artiq.language.units import ms, us
from ndscan.experiment import ExpFragment, FloatParam, NumberValue
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle, IntParamHandle
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import VDrivenSupply
from repository.utils.get_local_devices import get_local_devices

#logger: logging.Logger = logging.getLogger(name=__name__)


class SinusoidalFrequencyModulation(ExpFragment):
    def build_fragment(self):
        """
        Frequency modulation experiment

        This ExpFragment just breaks out the functionality of:class:`.SUServoFrag`.
        """

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
        self.setattr_fragment("modulation", SetSupplies, [current_config], init=False)
        self.setter: SetSupplies

        # Experimental parameters
        self.setattr_param(
            name="laser_wavelength",
            param_class=FloatParam,
            description="Laser wavelength",
            default=852.0,
            # unit="nm",
            min=780.0,
            max=1064.0,
        )
        self.laser_wavelength: FloatParamHandle
        # Convert wavelength to frequency
        self.f_c = (
            2.99792458 / self.laser_wavelength.get()
        ) * 1e8  # Carrier Frequency (in MHz)

        self.setattr_param(
            name="f_dev",
            param_class=FloatParam,
            description="Frequency deviation",
            default=0.0,
            unit="MHz",
            min=-1.0,
            max=1.0,
        )
        self.f_dev: FloatParamHandle

        self.setattr_param(
            name="f_m",
            param_class=FloatParam,
            description="Modulation frequency",
            default=10.0,
            unit="MHz",
            min=-210.0,
            max=210.0,
        )
        self.f_m: FloatParamHandle

        self.setattr_param(
            name="n_steps",
            param_class=NumberValue,
            description="Number of time steps",
            default=1000,
            unit=None,
        )
        self.n_steps: IntParamHandle

        self.setattr_param(
            name="dt",
            param_class=FloatParam,
            description="Time per step",
            default=1e-3 * ms,
            unit="microseconds",
        )
        self.dt: FloatParamHandle

        # Unlock laser
        unlocks = [dev for dev in get_local_devices(self, TTLInOut) if "unlock" in dev]
        self.setattr_argument("ttl", EnumerationValue(unlocks))  # ttl 5
        self.ttl: str
        if self.ttl is not None:
            self.unlock_ttl: TTLInOut = self.get_device(self.ttl)
        else:
            self.unlock_ttl: TTLInOut = self.get_device(unlocks[0])

        self.setattr_device("urukul")  # Urukul channel
        self.urukul: str

    @kernel
    def run_once(self):
        self.core.reset()
        self.urukul.init()
        self.urukul.set(attenuation=0.0)  # Set attenuation if needed

        # Example Parameters
        # f_c = 100e6      # Carrier frequency (Hz)
        # f_dev = 1e6      # Frequency deviation (Hz)
        # f_m = 1e3        # Modulation frequency (Hz)
        # n_steps = 1000   # Number of time steps
        # dt = 1e-6        # Time per step (seconds)
        # Sweep frequency sinusoidally

        for i in range(self.n_steps):
            t = i * self.dt
            freq = self.f_c + self.f_dev * math.sin(2 * math.pi * self.f_m * t)
            self.urukul.set(frequency=freq, amplitude=1.0)
            delay(self.dt)


FrequencyModulation = make_fragment_scan_exp(SinusoidalFrequencyModulation)


# Template for making new attributes
# self.setattr_param(
#     "attribute_name",
#     param_class=,
#     description="",
#     default=,
#     unit="",
#     min=,
#     max=,
# )
