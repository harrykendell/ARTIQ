from artiq.experiment import EnvExperiment, kernel
from artiq.language import delay, us

from artiq.coredevice.core import Core
from artiq.coredevice.fastino import Fastino

from repository.models import VDrivenSupply


# Numbers obtained by inverting Fastino voltage_to_mu. The positive endpoint is
# slightly below +10 V, matching the coredevice conversion.
FASTINO_MIN = (-0x8000) / (0x8000 / 10.0)
FASTINO_MAX = (0xFFFF - 0x8000) / (0x8000 / 10.0)


class FastinoManager:
    """Non-persistent raw Fastino control retained for diagnostic compatibility.

    Raw DAC voltages and LED states are held only in memory. This manager does
    not create ``fastino.voltages`` or ``fastino.leds`` datasets.
    """

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        fastino: Fastino,
        name: str = "fastino",
        restore: bool = True,
    ):
        self.experiment = experiment
        self.core: Core = core
        self.fastino = fastino
        self.name = name
        self.unit = "V"
        self.MIN = FASTINO_MIN
        self.MAX = FASTINO_MAX

        self.voltages = [0.0] * 32
        self.leds = [0] * 8

        if restore:
            self.set_all()

    def _led_mask(self) -> int:
        mask = 0
        for index, value in enumerate(self.leds):
            mask |= (int(value) & 0b1) << index
        return mask

    def set_led(self, ch: int, value: int) -> None:
        """Set one Fastino front-panel LED without persisting it."""
        self.leds[ch] = int(value) & 0b1
        self._set_leds_hardware(self._led_mask())

    def set_leds(self, bitmask: int) -> None:
        """Set all Fastino front-panel LEDs without persisting them."""
        self.leds = [bitmask >> index & 0b1 for index in range(8)]
        self._set_leds_hardware(bitmask)

    def set_voltage(self, ch: int, voltage: float) -> float:
        """Set one raw Fastino DAC voltage without creating datasets."""
        voltage = min(max(float(voltage), self.MIN), self.MAX)
        self.voltages[ch] = voltage

        update_leds = ch < len(self.leds)
        if update_leds:
            self.leds[ch] = 1 if voltage != 0.0 else 0

        self._set_channel_hardware(
            ch,
            voltage,
            self._led_mask(),
            update_leds,
        )
        return voltage

    def get_voltage(self, ch: int) -> float:
        return self.voltages[ch]

    def set_all(self) -> None:
        """Apply the current in-memory raw state."""
        for channel, voltage in enumerate(self.voltages):
            self._set_dac_hardware(channel, voltage)
        self._set_leds_hardware(self._led_mask())

    @kernel
    def _set_dac_hardware(self, channel, voltage):
        self.core.break_realtime()
        self.fastino.set_dac(channel, voltage)

    @kernel
    def _set_leds_hardware(self, led_mask):
        self.core.break_realtime()
        self.fastino.set_leds(led_mask)

    @kernel
    def _set_channel_hardware(self, channel, voltage, led_mask, update_leds):
        self.core.break_realtime()
        self.fastino.set_dac(channel, voltage)
        if update_leds:
            # Fastino DAC and LED writes use the same RTIO channel. Neither
            # coredevice method advances the timeline, so separate them.
            delay(1 * us)
            self.fastino.set_leds(led_mask)


class DeltaElektronikaManager(FastinoManager):
    """Legacy fixed 0-5 V to 0-10 A Delta Elektronika mapping.

    This compatibility manager is now non-persistent. The configured
    :class:`VDrivenSupplyManager` should be used for normal lab operation.
    """

    def __init__(self, experiment, core, fastino, name="fastino"):
        super().__init__(experiment, core, fastino, name)

        self.unit = "A"
        self.voltage_range = [0, 5]
        self.current_range = [0, 10]

    @staticmethod
    def convert_range(value, old_range, new_range):
        return (value - old_range[0]) / (old_range[1] - old_range[0]) * (
            new_range[1] - new_range[0]
        ) + new_range[0]

    def VtoI(self, voltage):
        return self.convert_range(voltage, self.voltage_range, self.current_range)

    def ItoV(self, current):
        return self.convert_range(current, self.current_range, self.voltage_range)

    def set_current(self, ch, current):
        return self.set_voltage(ch, self.ItoV(current))

    def get_current(self, ch):
        return self.VtoI(self.voltages[ch])


class VDrivenSupplyManager:
    """Manage named :class:`VDrivenSupply` objects attached to one Fastino.

    The authoritative runtime state is stored only in the per-supply datasets::

        <fastino>.<name>.output
        <fastino>.<name>.enabled

    ``output`` is stored in ARTIQ base units and tagged with the unit from
    ``devices.py``. For example, ``100 * MHz`` is stored as ``100e6`` while the
    GUI displays ``100 MHz``. Applied DAC voltages and the Fastino LED mask are
    derived from these datasets and the current ``devices.py`` configuration;
    no raw ``<fastino>.voltages`` or ``<fastino>.leds`` datasets are used.
    """

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        fastino: Fastino,
        supplies: list[VDrivenSupply],
        name: str = "fastino",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.fastino = fastino
        self.name = name
        self.MIN = FASTINO_MIN
        self.MAX = FASTINO_MAX

        configured = [supply for supply in supplies if supply.fastino == name]
        self.supplies = sorted(configured, key=lambda supply: (supply.ch, supply.name))

        if not self.supplies:
            raise ValueError(f"No VDrivenSupplies are configured for {name!r}")

        supply_names = [supply.name for supply in self.supplies]
        channels = [supply.ch for supply in self.supplies]

        if len(supply_names) != len(set(supply_names)):
            raise ValueError("VDrivenSupply names must be unique")
        if len(channels) != len(set(channels)):
            raise ValueError(
                f"Multiple VDrivenSupplies are configured on the same {name} channel"
            )

        for supply in self.supplies:
            if not 0 <= supply.ch < 32:
                raise ValueError(
                    f"VDrivenSupply {supply.name!r} has invalid Fastino channel "
                    f"{supply.ch}; expected 0-31"
                )
            if supply.gain == 0:
                raise ValueError(f"VDrivenSupply {supply.name!r} has zero gain")

        self.by_name = {supply.name: supply for supply in self.supplies}
        self.outputs: dict[str, float] = {}
        self.enabled: dict[str, bool] = {}

        for supply in self.supplies:
            output_path = self._output_dataset(supply.name)
            enabled_path = self._enabled_dataset(supply.name)

            output = float(
                experiment.get_dataset(
                    output_path,
                    default=float(supply.default_output),
                )
            )
            output = self.clamp_output(supply.name, output)

            enabled = bool(
                experiment.get_dataset(
                    enabled_path,
                    default=bool(supply.default_enabled),
                )
            )
            enabled = enabled and not supply.disabled

            self.outputs[supply.name] = output
            self.enabled[supply.name] = enabled
            self._persist_output(supply, output)
            self._persist_enabled(supply.name, enabled)

        self.restore_all()

    def _output_dataset(self, supply_name: str) -> str:
        return f"{self.name}.{supply_name}.output"

    def _enabled_dataset(self, supply_name: str) -> str:
        return f"{self.name}.{supply_name}.enabled"

    def _persist_output(self, supply: VDrivenSupply, output: float) -> None:
        self.experiment.set_dataset(
            self._output_dataset(supply.name),
            float(output),
            persist=True,
            broadcast=True,
            unit=supply.unit,
        )

    def _persist_enabled(self, supply_name: str, enabled: bool) -> None:
        self.experiment.set_dataset(
            self._enabled_dataset(supply_name),
            bool(enabled),
            persist=True,
            broadcast=True,
        )

    def get_limits(self, supply_name: str) -> tuple[float, float]:
        """Return limits imposed by both devices.py and the Fastino range."""
        supply = self.by_name[supply_name]

        hardware_outputs = sorted((self.MIN * supply.gain, self.MAX * supply.gain))
        minimum = max(float(supply.min_output), hardware_outputs[0])
        maximum = min(float(supply.max_output), hardware_outputs[1])

        if minimum > maximum:
            raise ValueError(
                f"VDrivenSupply {supply.name!r} range "
                f"[{supply.min_output}, {supply.max_output}] cannot be generated "
                f"with gain {supply.gain} over the Fastino voltage range "
                f"[{self.MIN}, {self.MAX}]"
            )

        return minimum, maximum

    def clamp_output(self, supply_name: str, output: float) -> float:
        minimum, maximum = self.get_limits(supply_name)
        return min(max(float(output), minimum), maximum)

    def get_output(self, supply_name: str) -> float:
        """Return the retained physical setpoint, including while disabled."""
        return self.outputs[supply_name]

    def get_enabled(self, supply_name: str) -> bool:
        return self.enabled[supply_name]

    def get_applied_voltage(self, supply_name: str) -> float:
        """Derive the voltage currently requested from the named state."""
        supply = self.by_name[supply_name]
        if not self.enabled[supply_name] or supply.disabled:
            return 0.0
        voltage = self.outputs[supply_name] / supply.gain
        return min(max(float(voltage), self.MIN), self.MAX)

    def set_output(self, supply_name: str, output: float) -> float:
        """Retain a physical output and apply it immediately when enabled."""
        supply = self.by_name[supply_name]
        output = self.clamp_output(supply_name, output)
        self.outputs[supply_name] = output
        self._persist_output(supply, output)

        if self.enabled[supply_name] and not supply.disabled:
            self._apply_supply(supply)

        return output

    def set_enabled(self, supply_name: str, enabled: bool) -> bool:
        """Enable/disable a supply without discarding its retained setpoint."""
        supply = self.by_name[supply_name]
        enabled = bool(enabled) and not supply.disabled
        self.enabled[supply_name] = enabled
        self._persist_enabled(supply_name, enabled)
        self._apply_supply(supply)
        return enabled

    def restore_all(self) -> None:
        """Restore all DACs and then set the derived LED mask once."""
        for supply in self.supplies:
            self._set_dac_hardware(
                supply.ch,
                self.get_applied_voltage(supply.name),
            )
        self._set_leds_hardware(self._led_mask())

    def turn_off(self) -> None:
        """Disable every configured supply while retaining all setpoints."""
        for supply in self.supplies:
            self.enabled[supply.name] = False
            self._persist_enabled(supply.name, False)
        self.restore_all()

    def _led_mask(self) -> int:
        mask = 0
        for supply in self.supplies:
            if supply.ch < 8 and self.enabled[supply.name] and not supply.disabled:
                mask |= 1 << supply.ch
        return mask

    def _apply_supply(self, supply: VDrivenSupply) -> None:
        self._set_channel_hardware(
            supply.ch,
            self.get_applied_voltage(supply.name),
            self._led_mask(),
            supply.ch < 8,
        )

    @kernel
    def _set_dac_hardware(self, channel, voltage):
        self.core.break_realtime()
        self.fastino.set_dac(channel, voltage)

    @kernel
    def _set_leds_hardware(self, led_mask):
        self.core.break_realtime()
        self.fastino.set_leds(led_mask)

    @kernel
    def _set_channel_hardware(self, channel, voltage, led_mask, update_leds):
        """Apply one voltage and, where applicable, the derived LED mask."""
        self.core.break_realtime()
        self.fastino.set_dac(channel, voltage)
        if update_leds:
            # Fastino DAC and LED writes use the same RTIO channel. Neither
            # coredevice method advances the timeline, so separate them.
            delay(1 * us)
            self.fastino.set_leds(led_mask)
