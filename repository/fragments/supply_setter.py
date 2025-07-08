import logging
from typing import List

from artiq.coredevice.core import Core
from artiq.coredevice.fastino import Fastino
from artiq.experiment import TFloat, TInt32, TList, kernel, portable
from artiq.language import at_mu, delay_mu, now_mu
from ndscan.experiment import Fragment
from repository.models import VDrivenSupply

logger = logging.getLogger(__name__)


class SetSupplies(Fragment):
    """
    Set multiple supplies that are controlled by a analog voltages.
    The supplies must all be controlled by the same fastino

    The channel to be set should be passed as an argument to
    :meth:`.build_fragment`, e.g.::

        self.setattr_fragment(
            "coil_setter",
            SetSupplies,
            [VDrivenSupply["X1"]],
            init=False,
        )
    """

    def build_fragment(self, configs: List[VDrivenSupply], init: bool = False):
        self.setattr_device("core")
        self.core: Core
        if type(configs) is not list:
            configs = [configs]
        self.configs: list[VDrivenSupply] = configs
        self.defaults = [dev.default_output for dev in self.configs]
        assert all(
            [c.fastino == self.configs[0].fastino for c in self.configs]
        ), "All supplies must use the same Fastino"

        self.fastino = self.get_device(self.configs[0].fastino)
        self.fastino: Fastino

        self.fastino_channels = [c.ch for c in self.configs]

        # Kernel variables
        self.first_run = init
        self.debug_enabled = logger.isEnabledFor(logging.INFO)
        self.num_supplies = len(self.configs)

        # Kernel invariants
        kernel_invariants = getattr(self, "kernel_invariants", set())
        self.kernel_invariants = kernel_invariants | {
            "debug_enabled",
            "num_supplies",
            "configs",
            "fastino",
            "fastino_channels",
        }

    @kernel
    def device_setup(self) -> None:
        if self.first_run:
            if self.debug_enabled:
                logger.info("Initiating Fastino %s", self.fastino)

            self.core.break_realtime()
            self.fastino.init()
            self.fastino.set_continuous(
                0xFFFFFFFF  # set continous bitmask for all 32 channels
            )

            self.first_run = False

        self.device_setup_subfragments()

    @portable
    def _single_output_to_volts(self, output: TFloat, supply_idx: TInt32):
        gain = self.configs[supply_idx].gain
        minlim = self.configs[supply_idx].min_output
        if output < minlim:
            logger.warning(
                "Output %s below min output %s for supply %s",
                output,
                minlim,
                self.configs[supply_idx].name,
            )
            return minlim / gain
        lim = self.configs[supply_idx].max_output
        if output > lim:
            logger.warning(
                "Output %s exceeds max output %s for supply %s",
                output,
                lim,
                self.configs[supply_idx].name,
            )
            return lim / gain
        return output / gain

    @portable
    def _outputs_to_volts(self, outputs: TList(TFloat), voltages_out: TList(TFloat)):
        if len(outputs) != len(self.configs):
            raise ValueError("Wrong number of outputs")

        if len(outputs) != len(voltages_out):
            raise ValueError("Output array is wrong size")

        for i in range(len(self.configs)):
            voltages_out[i] = self._single_output_to_volts(outputs[i], i)

    @kernel
    def set_outputs(self, outputs: TList(TFloat)):
        """
        Set outputs in their units.

        This method advances the timeline by 8ns * len(outputs) but also requires
        slack at least 1.5us + 808ns * len(outputs) on a Kasli 1.x as SPI events are
        written into the past.
        """
        voltages = [0.0] * len(self.configs)

        self._outputs_to_volts(outputs, voltages)

        if self.debug_enabled:
            slack_mu = now_mu() - self.core.get_rtio_counter_mu()
            logger.info(
                "Setting outputs = %s via voltages = %s on channels %s",
                outputs,
                voltages,
                self.fastino_channels,
            )
            at_mu(self.core.get_rtio_counter_mu() + slack_mu)

        for idx in range(len(self.fastino_channels)):
            self.fastino.set_dac(self.fastino_channels[idx], voltages[idx])
            delay_mu(
                8
            )  # TODO: Nothing happens for multiple channels if we use a shorter delay?!

    @kernel
    def set_to_defaults(self):
        """
        Set the outputs to the default values defined in the configs
        """
        self.set_outputs(
            [0.0 if dev.disabled else dev.default_output for dev in self.configs]
        )

    @kernel
    def turn_off(self):
        """
        Convenience method to turn off all supplies
        """
        self.set_outputs([0.0] * len(self.configs))
