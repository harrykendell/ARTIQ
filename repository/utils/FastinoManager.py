from artiq.experiment import *
from artiq.language import us, ms, MHz, dB, delay, TInt64

from artiq.coredevice.core import Core, rtio_get_counter, at_mu
from artiq.coredevice.fastino import Fastino


class FastinoManager:  # {{{
    """
    Manages a Fastino device

    Data is loaded from the device params
    """

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        fastino: Fastino,
        name="fastino",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.fastino = fastino
        self.name = name

        self.MIN = (-0x8000) / (0x8000 / 10.0) # number from inverting the voltage_to_mu for fastino
        self.MAX = (0xFFFF - 0x8000) / (0x8000 / 10.0) # NB these can be extended as round allows +-0.5 but as the inequality is strict we can't reach the limit anyway

        datasets = [
            "voltages",
            "leds",
        ]
        defaults = [
            [0.0] * 32,
            [0b0] * 8,
        ]
        units = [
            None,
            None,
        ]
        for dataset, default, unit in zip(datasets, defaults, units):
            temp = experiment.get_dataset(name + "." + dataset, default=default)
            # we set the values back so we are allowed to mutate then later
            experiment.set_dataset(
                name + "." + dataset,
                temp,
                persist=True,
                unit=unit,
            )
            self.__dict__[dataset] = temp

        self.set_all()

    @kernel
    def _mutate_and_set_float(self, dataset, variable, index, value):
        """Mutate the dataset and change our internal store of the value
        We have to pass both the dataset reference and local variable as __dict__ access is illegal on kernel
        """
        self.experiment.mutate_dataset(self.name + "." + dataset, index, value)
        variable[index] = value
        delay(50 * ms)

    @kernel
    def _mutate_and_set_leds(self, values):
        """Mutate the dataset and change our internal store of the values"""
        for i in range(len(values)):
            self.experiment.mutate_dataset(self.name + ".leds", i, values[i])
            self.leds[i] = values[i]
            delay(50 * ms)

        self.core.break_realtime()

    @kernel
    def set_led(self, ch, value):
        """sets a single led"""
        bitmask = 0
        for i in range(len(self.leds)):
            bitmask += (self.leds[i] & 0b1 if i != ch else value & (0b1)) << i
        self.set_leds(bitmask)

    @kernel
    def set_leds(self, bitmask):
        """sets all leds given a bitmask"""
        vals = [bitmask >> i & 0b1 for i in range(8)]
        self._mutate_and_set_leds(vals)

        self.fastino.set_leds(bitmask)

    @kernel
    def set_voltage(self, ch, voltage):
        self._mutate_and_set_float("voltages", self.voltages, ch, voltage)
        self.core.break_realtime()
        self.fastino.set_dac(
            ch, min(max(voltage, self.MIN), self.MAX) # number from inverting the voltage_to_mu for fastino
        )
        self.set_led(ch, 1 if voltage != 0 else 0)

        print("Set voltage", ch, voltage)

    @kernel
    def set_all(self):
        """
        Ensures the Fastino is set to the current state of the manager
        Where possible we extract state and update the dataset
        """

        # Prepare core
        self.core.break_realtime()

        # Initialize Fastino
        self.fastino.init()
        delay(200 * us)

        # Set LEDs
        self.fastino.set_leds(0b00000000)
        delay(100 * us)

        # Set DACs
        for i in range(len(self.voltages)):
            self.fastino.set_dac(i, self.voltages[i])
            delay(100 * us)
