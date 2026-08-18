from artiq.language import kernel, EnvExperiment, us, ms, MHz, V, dB, delay

from artiq.coredevice.core import Core
from artiq.coredevice.suservo import SUServo, Channel as SUServoChannel
from artiq.coredevice.ttl import TTLInOut

import numpy as np


class SUServoManager:  # {{{
    """Manage configured SUServo beams through semantic scalar datasets."""

    def __init__(
        self,
        experiment: EnvExperiment,
        core: Core,
        suservo: SUServo,
        suservo_chs: list[SUServoChannel],
        shutters: list[TTLInOut],
        beams,
        shutter_infos,
        name="suservo",
    ):
        self.experiment = experiment
        self.core: Core = core
        self.suservo: SUServo = suservo
        self.channels: list[SUServoChannel] = suservo_chs
        self.shutters: list[TTLInOut] = shutters
        self.beams = list(beams)
        self.shutter_infos = list(shutter_infos)
        self.name = name

        assert len(self.channels) == 8, "There must be 8 channels per SUServo"
        if len(self.beams) != len(self.channels):
            raise ValueError("Configure exactly one SUServoedBeam per SUServo channel")
        if len(self.shutter_infos) != len(self.shutters):
            raise ValueError("Shutter definitions and hardware devices must correspond")
        if len({beam.name for beam in self.beams}) != len(self.beams):
            raise ValueError("SUServoedBeam names must be unique")
        if len({shutter.name for shutter in self.shutter_infos}) != len(
            self.shutter_infos
        ):
            raise ValueError("Shutter names must be unique")
        enabled_path = f"{name}.enabled"
        self.enabled = bool(experiment.get_dataset(enabled_path, default=True))
        self._persist(enabled_path, self.enabled)

        self.gains, self.gain_datasets = self._load_beam_values(
            "gain", [beam.gain for beam in self.beams], integer=True
        )
        self.atts, self.attenuation_datasets = self._load_beam_values(
            "attenuation",
            [beam.attenuation for beam in self.beams],
            unit="dB",
            scale=dB,
        )
        self.freqs, self.frequency_datasets = self._load_beam_values(
            "frequency",
            [beam.frequency for beam in self.beams],
            unit="MHz",
            scale=MHz,
        )
        self.en_outs, self.output_enabled_datasets = self._load_beam_values(
            "output_enabled",
            [beam.output_enabled for beam in self.beams],
            boolean=True,
        )
        self.ys, self.y_datasets = self._load_beam_values(
            "y", [beam.initial_amplitude for beam in self.beams]
        )
        self.en_iirs, self.iir_enabled_datasets = self._load_beam_values(
            "iir_enabled",
            [beam.servo_enabled for beam in self.beams],
            boolean=True,
        )
        self.offsets, self.offset_datasets = self._load_beam_values(
            "offset", [beam.setpoint for beam in self.beams], unit="V", scale=V
        )
        self.Ps, self.p_datasets = self._load_beam_values(
            "p", [beam.p for beam in self.beams]
        )
        self.Is, self.i_datasets = self._load_beam_values(
            "i", [beam.i for beam in self.beams]
        )
        self.Gls, self.gl_datasets = self._load_beam_values(
            "gl", [beam.gl for beam in self.beams]
        )
        self.calib_gains, _ = self._load_beam_values(
            "calib_gain", [beam.calib_gain for beam in self.beams]
        )
        self.calib_offsets, _ = self._load_beam_values(
            "calib_offset", [beam.calib_offset for beam in self.beams], unit="V"
        )

        self.en_shutters = []
        self.shutter_datasets = []
        for shutter in self.shutter_infos:
            path = f"shutter.{shutter.name}.open"
            value = bool(experiment.get_dataset(path, default=shutter.enabled))
            self._persist(path, value)
            self.en_shutters.append(value)
            self.shutter_datasets.append(path)

        self.set_all()

    def _persist(self, path, value, unit=None):
        self.experiment.set_dataset(
            path,
            value,
            persist=True,
            broadcast=True,
            unit=unit,
        )

    def _load_beam_values(
        self, field, defaults, *, unit=None, scale=1.0, boolean=False, integer=False
    ):
        values = []
        paths = []
        for beam, default in zip(self.beams, defaults):
            path = f"{self.name}.{beam.name}.{field}"
            stored = self.experiment.get_dataset(path, default=default)
            if boolean:
                stored = bool(stored)
                value = stored
            elif integer:
                stored = int(stored)
                value = stored
            else:
                stored = float(stored)
                value = stored / scale
            self._persist(path, stored, unit=unit)
            values.append(value)
            paths.append(path)
        return values, paths

    @kernel
    def get_adc(self, ch):
        """
        Get the ADC value for a given channel
        Delays by 20us to ensure the servo was disabled
        """
        self.core.break_realtime()
        # self.suservo.set_config(0)
        # delay(50 * us)
        v = self.suservo.get_adc(ch)
        delay(50 * us)
        # self.suservo.set_config(self.enabled)
        # delay(50 * us)
        return v

    @kernel
    def get_y(self, ch: np.int64):
        """
        Get the Y value for a given channel
        Delays by 20us to ensure the servo was disabled
        """
        self.core.break_realtime()
        # self.suservo.set_config(0)
        # delay(50 * us)
        y = self.channels[ch].get_y(ch)
        delay(50 * us)
        # self.suservo.set_config(self.enabled)
        # delay(50 * us)
        return y

    def enable_servo(self):
        self.enabled = True
        self._persist(f"{self.name}.enabled", True)
        self._set_servo_enabled_hardware(True)

    def disable_servo(self):
        self.enabled = False
        self._persist(f"{self.name}.enabled", False)
        self._set_servo_enabled_hardware(False)

    @kernel
    def _set_servo_enabled_hardware(self, enabled):
        self.core.break_realtime()
        self.suservo.set_config(enable=1 if enabled else 0)

    def enable(self, ch: np.int32):
        """Enable a given channel"""
        self.en_outs[ch] = True
        self._persist(self.output_enabled_datasets[ch], True)
        self._set_output_enabled_hardware(ch, True)

    def disable(self, ch: np.int32):
        """Disable a given channel"""
        self.en_outs[ch] = False
        self._persist(self.output_enabled_datasets[ch], False)
        self._set_output_enabled_hardware(ch, False)

    @kernel
    def _set_output_enabled_hardware(self, ch, enabled):
        self.core.break_realtime()
        self.channels[ch].set(
            en_out=1 if enabled else 0,
            en_iir=1 if self.en_iirs[ch] else 0,
            profile=ch,
        )

    def set_gain(self, ch, gain):
        self.gains[ch] = int(gain)
        self._persist(self.gain_datasets[ch], self.gains[ch])
        self._set_gain_hardware(ch, self.gains[ch])

    @kernel
    def _set_gain_hardware(self, ch, gain):
        self.core.break_realtime()
        self.suservo.set_pgia_mu(ch, gain)

    def set_att(self, ch, att):
        self.atts[ch] = float(att)
        self._persist(self.attenuation_datasets[ch], self.atts[ch] * dB, unit="dB")
        self._set_att_hardware(ch, self.atts[ch])

    @kernel
    def _set_att_hardware(self, ch, att):
        # We have to write all 4 channels at once -
        # so convert each to mu and accumulate into reg
        reg = 0
        for i in range(4):
            reg += self.suservo.cplds[0].att_to_mu(
                self.atts[i if ch < 4 else 4 + i]
            ) << (i * 8)

        self.core.break_realtime()
        self.suservo.cplds[ch // 4].set_all_att_mu(reg)

    @kernel
    def offset_to_mu(self, setpoint, ch=0):
        """
        Convert a setpoint in V to the corresponding mu value
        """
        return -setpoint * (10.0 ** (self.gains[ch] - 1))

    def set_dds(self, ch: np.int32, freq, offset):
        """
        Frequency is in MHz
        Offset in V
        """
        if freq < 0.0 or freq > 400.0:
            raise ValueError("Frequency out of range")
        self.freqs[ch] = float(freq)
        self.offsets[ch] = float(offset)
        self._persist(self.frequency_datasets[ch], self.freqs[ch] * MHz, unit="MHz")
        self._persist(self.offset_datasets[ch], self.offsets[ch] * V, unit="V")
        self._set_dds_hardware(ch, self.freqs[ch], self.offsets[ch])

    @kernel
    def _set_dds_hardware(self, ch, freq, offset):
        self.core.break_realtime()
        self.channels[ch].set_dds(
            profile=ch,
            frequency=freq * MHz,
            offset=self.offset_to_mu(offset, ch),
        )

    def set_freq(self, ch: np.int32, freq):
        """
        Frequency is in MHz
        """
        self.set_dds(ch, freq, self.offsets[ch])

    def set_offset(self, ch: np.int32, offset):
        """
        Offset is in V
        """
        self.set_dds(ch, self.freqs[ch], offset)

    def set_y(self, ch: np.int32, y):
        self.ys[ch] = float(y)
        self._persist(self.y_datasets[ch], self.ys[ch])
        self._set_y_hardware(ch, self.ys[ch])

    @kernel
    def _set_y_hardware(self, ch, y):
        self.core.break_realtime()
        self.channels[ch].set_y(profile=ch, y=y)

    def set_iir(self, ch: np.int32, adc, P, I, Gl):  # noqa: E741
        self.Ps[ch] = float(P)
        self.Is[ch] = float(I)
        self.Gls[ch] = float(Gl)
        self._persist(self.p_datasets[ch], self.Ps[ch])
        self._persist(self.i_datasets[ch], self.Is[ch])
        self._persist(self.gl_datasets[ch], self.Gls[ch])
        self._set_iir_hardware(ch, adc, self.Ps[ch], self.Is[ch], self.Gls[ch])

    @kernel
    def _set_iir_hardware(self, ch, adc, P, I, Gl):  # noqa: E741
        self.core.break_realtime()
        self.channels[ch].set_iir(profile=ch, adc=adc, kp=P, ki=I, g=Gl)

    def enable_iir(self, ch: np.int32):
        self.en_iirs[ch] = True
        self._persist(self.iir_enabled_datasets[ch], True)
        self._set_iir_enabled_hardware(ch, True)

    def disable_iir(self, ch: np.int32):
        self.en_iirs[ch] = False
        self._persist(self.iir_enabled_datasets[ch], False)
        self._set_iir_enabled_hardware(ch, False)

    @kernel
    def _set_iir_enabled_hardware(self, ch, enabled):
        self.core.break_realtime()
        self.channels[ch].set(
            en_out=1 if self.en_outs[ch] else 0,
            en_iir=1 if enabled else 0,
            profile=ch,
        )
        if not enabled:
            delay(10 * us)
            self.channels[ch].set_y(profile=ch, y=self.ys[ch])

    def open_shutter(self, ch):
        """Enable a given shutter"""
        self.en_shutters[ch] = True
        self._persist(self.shutter_datasets[ch], True)
        self._set_shutter_hardware(ch, True)

    def close_shutter(self, ch):
        """Disable a given shutter"""
        self.en_shutters[ch] = False
        self._persist(self.shutter_datasets[ch], False)
        self._set_shutter_hardware(ch, False)

    @kernel
    def _set_shutter_hardware(self, ch, opened):
        self.core.break_realtime()
        if opened:
            self.shutters[ch].on()
        else:
            self.shutters[ch].off()

    def set_all(self):
        """Restore all configured state without rewriting its datasets."""
        self._set_all_hardware()

    @kernel
    def _set_all_hardware(self):
        # Prepare core
        self.core.break_realtime()
        self.suservo.set_config(enable=0)
        delay(50 * ms)
        self.suservo.init()
        delay(150 * ms)

        # shutters
        for shutter in range(len(self.shutters)):
            if self.en_shutters[shutter]:
                self.shutters[shutter].on()
            else:
                self.shutters[shutter].off()

        delay(10 * ms)
        self.core.break_realtime()

        for ch in range(len(self.channels)):
            self.core.break_realtime()
            # set gain on Sampler channel  to 10^gain - these are wiped in the init
            self.suservo.set_pgia_mu(ch, self.gains[ch])

            # Set profile parameters
            self.channels[ch].set_dds(
                profile=ch,
                frequency=self.freqs[ch] * MHz,
                offset=self.offset_to_mu(self.offsets[ch], ch),
            )

            delay(200 * us)
            # PI loop params
            self.channels[ch].set_iir(
                profile=ch,
                adc=ch,
                kp=self.Ps[ch],
                ki=self.Is[ch],
                g=self.Gls[ch],
            )
            delay(20 * us)
            self.channels[ch].set_y(profile=ch, y=self.ys[ch])

        for ch in range(len(self.channels)):
            # set attenuation on all 4 channels -
            # we set all from the dataset then overwrite the one we want
            self.suservo.cplds[ch // 4].set_att(ch % 4, self.atts[ch])
            self.channels[ch].set(
                en_out=1 if self.en_outs[ch] else 0,
                en_iir=1 if self.en_iirs[ch] else 0,
                profile=ch,
            )
            delay(5 * 1.2 * us)

        self.suservo.set_config(enable=1 if self.enabled else 0)
