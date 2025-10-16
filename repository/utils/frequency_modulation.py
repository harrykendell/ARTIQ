##################### Code for frequency modulation ########################

import numpy as np

# from artiq.experiment import *
import logging
from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import EnumerationValue, delay, kernel
from artiq.language.units import ms, us, MHz, kHz, V
from ndscan.experiment import ExpFragment, FloatParam, IntParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle, IntParamHandle
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import VDrivenSupply
from repository.utils.get_local_devices import get_local_devices
from artiq.language.core import kernel, now_mu, at_mu, delay_mu
from artiq.coredevice.core import Core
from artiq.coredevice.fastino import Fastino

logger = logging.getLogger(__name__)


class SinusoidalFrequencyModulation(ExpFragment):
    def build_fragment(self):
        """
        Frequency modulation experiment

        This ExpFragment just breaks out the functionality of:class:`.SUServoFrag`.
        """

        self.setattr_device("core")
        self.setattr_device("fastino")
        self.setattr_device("core_dma")
        self.core: Core
        self.fastino: Fastino
        self.core_dma: Core

        # Retrieve the laser to be modulated (default = 852 nm ECDL)

        lasers = [dev.name for dev in VDrivenSupply.values() if dev.unit == "MHz"]
        default = lasers[1]
        self.setattr_argument("laser", EnumerationValue(lasers, default=default))
        self.laser: str
        # self.gain = VDrivenSupply[self.laser].gain
        self.gain = 83.0 * MHz / V

        if self.laser is not None:
            current_config = VDrivenSupply[self.laser]
        else:
            current_config = VDrivenSupply[default]
        self.setattr_fragment("setter", SetSupplies, [current_config], init=False)
        self.setter: SetSupplies

        # Unlock the laser
        unlocks = [dev for dev in get_local_devices(self, TTLInOut) if "unlock" in dev]
        default = unlocks[0]
        self.setattr_argument("ttl", EnumerationValue(unlocks))  # ttl 5
        self.ttl: str
        if self.ttl is not None:
            self.unlock_ttl: TTLInOut = self.get_device(self.ttl)
        else:
            self.unlock_ttl: TTLInOut = self.get_device(default)

        # Experimental parameters

        self.setattr_param(
            name="f_dev",
            param_class=FloatParam,
            description="Frequency deviation",
            default=100 * MHz,
            unit="MHz",
            min=0.0 * MHz,
            max=210.0 * MHz,
        )
        self.f_dev: FloatParamHandle

        self.setattr_param(
            name="f_m",
            param_class=FloatParam,
            description="Modulation frequency",
            default=10.0 * kHz,
            unit="kHz",
            min=0.0 * kHz,
            max=1000.0 * kHz,
        )
        self.f_m: FloatParamHandle

        self.setattr_param(
            name="N",
            param_class=IntParam,
            description="Samples per cycle",
            default=64,
            min=8,
            max=100,
        )
        self.N: IntParamHandle

        self.setattr_param(
            name="V0",
            param_class=FloatParam,
            description="DC bias voltage",
            default=0.0 * V,
            unit="V",
        )
        self.V0: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.reset()

        # Example Parameters
        # N = 16                  # samples per cycle (typ. 16–64)
        # f_m = 10 kHz            # modulation frequency (up to 1000 kHz)
        # f_dev = 166.55 MHz      # frequency deviation (up to ±210 MHz)

        # ------------------------------------------------------------------------------#
        # Method 1
        # # Compute timing
        # samples_per_sec = (
        #     self.N.get() * self.f_m.get()
        # )  # sample_rate ≤ 0.9e6 (safety margin)

        # # Precompute kernel-invariant timing
        # dt = 1.0 / samples_per_sec  # seconds between sample/ time-steps

        # # hardware timing constraints (use mu to avoid float drift)
        # t_frame_mu = self.fastino.t_frame
        # margin_mu = self.core.seconds_to_mu(0 * us)  # small safety margin
        # step_mu = max(self.core.seconds_to_mu(dt), t_frame_mu + margin_mu)

        # # Precompute phase step for efficiency
        # phase_step = 2.0 * np.pi / float(self.N.get())

        # #  Record DMA sequence
        # with self.core_dma.record("sine_wave"):
        #     # phase = 0.0
        #     for i in range(self.N.get()):
        #         # t = i * self.dt
        #         phase = i * phase_step
        #         self.setter.set_outputs([self.f_dev.get() * np.sin(phase)])
        #         delay_mu(step_mu)

        #     # let the last write settle
        #     delay_mu(t_frame_mu + margin_mu)

        # ------------------------------------------------------------------------------#
        # Method 2
        # Compute timing
        samples_per_sec = (
            self.N.get() * self.f_m.get()
        )  # sample_rate ≤ 0.9e6 (safety margin)

        # Precompute kernel-invariant timing
        dt = 1.0 / samples_per_sec  # seconds between sample/ time-steps

        # # hardware timing constraints (use mu to avoid float drift)
        # t_frame_mu = self.fastino.t_frame
        # step_mu = max(
        #     self.core.seconds_to_mu(dt), t_frame_mu
        # )  # "Sample rate exceeds Fastino capability" - but check you cant go faster or anything
        
        
        step_mu = self.core.seconds_to_mu(dt)
        assert step_mu > self.fastino.t_frame

        # Precompute phase step for efficiency
        phase_step = 2.0 * np.pi / float(self.N.get())

        #  Record DMA sequence
        with self.core_dma.record("sine_wave"):
            for i in range(self.N.get()):
                phase = i * phase_step
                self.setter.set_outputs([self.f_dev.get() * np.sin(phase)])

                delay_mu(step_mu)
                print([self.f_dev.get() * np.sin(phase)])
                print(step_mu)

            # let the last write settle
            # delay_mu(t_frame_mu)
        # ------------------------------------------------------------------------------#

        # Play it back continuously
        handle = self.core_dma.get_handle("sine_wave")
        self.core.break_realtime()
        for _ in range(6000):  # play it back (n x 1e3) times, then return
            self.core_dma.playback_handle(handle)

        self.core.break_realtime()
        # Reset the laser
        self.setter.set_to_defaults()
        # Relock the laser

        # if self.reset.get():
        #     """
        #     Relock an ECDL

        #     Unpush and then after `time_to_shift` seconds, turn the TTL off
        #     """
        #     self.setter.set_to_defaults()
        #     delay(self.time_to_shift.get())
        #     self.unlock_ttl.off()
        #     logging.warning("Relocking %s", self.laser)
        # else:
        #     pass


Frequency_Modulation = make_fragment_scan_exp(SinusoidalFrequencyModulation)

# NB: Cannot assign frequencies to fastino0.set_dac() since this expects a voltage (±5 V range).
# Based on calibration (G = 83 MHz/V), 200 MHz --> 2.41V.
# This is what gets sent to the Fastino.
# logger: logging.Logger = logging.getLogger(name=__name__)


### Old version below - IGNORE ---

# laser_wavelength: float = 852.0e-9  # m
# f_c = (2.99792458 * 1e8) / (laser_wavelength) * 1e-6  # Carrier Frequency (in MHz)


# class SinusoidalFrequencyModulation(ExpFragment):
#     def build_fragment(self):
#         """
#         Frequency modulation experiment

#         This ExpFragment just breaks out the functionality of:class:`.SUServoFrag`.
#         """
#         nm = 1e-9  #
#         self.setattr_device("core")
#         self.core: Core
#         lasers = [dev.name for dev in VDrivenSupply.values() if dev.unit == "MHz"]
#         default = lasers[0]
#         print(default)
#         self.setattr_argument("laser", EnumerationValue(lasers, default=default))
#         self.laser: str

#         if self.laser is not None:
#             current_config = VDrivenSupply[self.laser]
#         else:
#             current_config = VDrivenSupply[default]
#         self.setattr_fragment("modulation", SetSupplies, [current_config], init=False)
#         self.setter: SetSupplies

#         # Experimental parameters
#         self.setattr_param(
#             name="laser_wavelength",
#             param_class=FloatParam,
#             description="Laser wavelength",
#             default=852.0,
#             # unit="nm",
#             min=780.0,
#             max=1064.0,
#         )
#         self.laser_wavelength: FloatParamHandle

#         self.setattr_param(
#             name="f_dev",
#             param_class=FloatParam,
#             description="Frequency deviation",
#             default=0.0 * MHz,
#             unit="MHz",
#             min=-2.0 * MHz,
#             max=2.0 * MHz,
#         )
#         self.f_dev: FloatParamHandle

#         self.setattr_param(
#             name="f_m",
#             param_class=FloatParam,
#             description="Modulation frequency",
#             default=10.0 * MHz,
#             unit="MHz",
#             min=-220.0 * MHz,
#             max=220.0 * MHz,
#         )
#         self.f_m: FloatParamHandle

#         self.setattr_param(
#             name="n_steps",
#             param_class=FloatParam,
#             description="Number of time steps",
#             default=1000.0,
#         )
#         self.n_steps: FloatParamHandle

#         self.setattr_param(
#             name="dt",
#             param_class=FloatParam,
#             description="Time per step",
#             default=1.0 * us,
#             unit="us",
#         )
#         self.dt: FloatParamHandle

#         # Unlock laser
#         unlocks = [dev for dev in get_local_devices(self, TTLInOut) if "unlock" in dev]
#         self.setattr_argument("ttl", EnumerationValue(unlocks))  # ttl 5
#         self.ttl: str
#         if self.ttl is not None:
#             self.unlock_ttl: TTLInOut = self.get_device(self.ttl)
#         else:
#             self.unlock_ttl: TTLInOut = self.get_device(unlocks[0])

#         self.setattr_device("urukul")  # Urukul channel
#         self.urukul: str

#     @kernel
#     def run_once(self):
#         self.core.reset()

#         self.urukul.init()
#         self.urukul.set(attenuation=0.0)  # Set attenuation if needed

#         # Example Parameters
#         # f_c = 100e6 (100MHz)     # Carrier frequency (Hz)
#         # f_dev = 1e6 (1MHz)     # Frequency deviation (Hz)
#         # f_m = 1e3    (1e-3 MHz)    # Modulation frequency (Hz)
#         # n_steps = 1000   # Number of time steps
#         # dt = 1e-6 (1 microseconds)       # Time per step (seconds)
#         # Sweep frequency sinusoidally

#         for i in range(self.n_steps):
#             t = i * self.dt
#             freq = self.f_c + self.f_dev * math.sin(2 * math.pi * self.f_m * t)
#             self.urukul.set(frequency=freq, amplitude=1.0)
#             delay(self.dt)


# FrequencyModulation = make_fragment_scan_exp(SinusoidalFrequencyModulation)
