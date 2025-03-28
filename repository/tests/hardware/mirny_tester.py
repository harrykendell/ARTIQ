#!/usr/bin/env python3
import sys

sys.path.append(
    __file__.split("repository")[0] + "repository"
)  # link to repository root

from artiq.experiment import *
from artiq.master.databases import DeviceDB
from artiq.master.worker_db import DeviceManager

from utils.wait_for_enter import is_enter_pressed

from artiq.coredevice.core import Core
from artiq.coredevice.mirny import Mirny
from artiq.coredevice.adf5356 import ADF5356
from artiq.coredevice.almazny import AlmaznyChannel, AlmaznyLegacy


def chunker(seq, size):
    res = []
    for el in seq:
        res.append(el)
        if len(res) == size:
            yield res
            res = []
    if res:
        yield res


class MirnyTester(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core
        self.mirny_cplds: dict[Mirny] = dict()
        self.mirnies: dict[ADF5356] = dict()
        self.almaznys: dict[AlmaznyChannel] = dict()
        self.legacy_almaznys: dict[AlmaznyLegacy] = dict()

        ddb = self.get_device_db()
        for name, desc in ddb.items():
            if isinstance(desc, dict) and desc["type"] == "local":
                module, cls = desc["module"], desc["class"]
                if (module, cls) == ("artiq.coredevice.mirny", "Mirny"):
                    self.mirny_cplds[name] = self.get_device(name)
                elif (module, cls) == ("artiq.coredevice.adf5356", "ADF5356"):
                    self.mirnies[name] = self.get_device(name)
                elif (module, cls) == ("artiq.coredevice.almazny", "AlmaznyChannel"):
                    self.almaznys[name] = self.get_device(name)
                elif (module, cls) == ("artiq.coredevice.almazny", "AlmaznyLegacy"):
                    self.legacy_almaznys[name] = self.get_device(name)

        # guard against the whole DummyDevice shit
        if self.mirnies and type(self.mirnies[next(iter(self.mirnies))]) is ADF5356:
            self.mirnies = sorted(
                self.mirnies.items(),
                key=lambda x: (x[1].cpld.bus.channel, x[1].channel),
            )

    @kernel
    def init_mirny(self, cpld):
        self.core.break_realtime()
        cpld.init()

    @kernel
    def setup_mirny(self, channel, frequency):
        self.core.break_realtime()
        channel.init()

        channel.set_att(11.5 * dB)
        channel.sw.on()
        self.core.break_realtime()

        channel.set_frequency(frequency * MHz)
        delay(5 * ms)

    @kernel
    def sw_off_mirny(self, channel):
        self.core.break_realtime()
        channel.sw.off()

    @kernel
    def mirny_rf_switch_wave(self, channels):
        while not is_enter_pressed():
            self.core.break_realtime()
            # do not fill the FIFOs too much to avoid long response times
            t = now_mu() - self.core.seconds_to_mu(0.2)
            while self.core.get_rtio_counter_mu() < t:
                pass
            for channel in channels:
                channel.pulse(100 * ms)
                delay(100 * ms)

            delay(100 * ms)

    @kernel
    def init_legacy_almazny(self, almazny):
        self.core.break_realtime()
        almazny.init()
        almazny.output_toggle(True)

    @kernel
    def legacy_almazny_set_attenuators_mu(self, almazny, ch, atts):
        self.core.break_realtime()
        almazny.set_att_mu(ch, atts)

    @kernel
    def legacy_almazny_att_test(self, almazny):
        # change attenuation bit by bit over time for all channels
        att_mu = 0
        while not is_enter_pressed():
            self.core.break_realtime()
            t = now_mu() - self.core.seconds_to_mu(0.5)
            while self.core.get_rtio_counter_mu() < t:
                pass
            for ch in range(4):
                almazny.set_att_mu(ch, att_mu)
            delay(250 * ms)
            if att_mu == 0:
                att_mu = 1
            else:
                att_mu = (att_mu << 1) & 0x3F

    @kernel
    def legacy_almazny_toggle_output(self, almazny, rf_on):
        self.core.break_realtime()
        almazny.output_toggle(rf_on)

    def test_legacy_almaznys(self):
        print("*** Testing legacy Almaznys (v1.1 or older).")
        for name, almazny in sorted(self.legacy_almaznys.items(), key=lambda x: x[0]):
            print(name + "...")
            print("Initializing Mirny CPLDs...")
            for name, cpld in sorted(self.mirny_cplds.items(), key=lambda x: x[0]):
                print(name + "...")
                self.init_mirny(cpld)
            print("...done")
            print("Testing attenuators. Frequencies:")
            for card_n, channels in enumerate(chunker(self.mirnies, 4)):
                for channel_n, (channel_name, channel_dev) in enumerate(channels):
                    frequency = 75 + card_n * 10 + channel_n * 1
                    print("Almazny freq: {}\t{}MHz".format(channel_name, frequency * 2))
                    self.setup_mirny(channel_dev, frequency)
            self.init_legacy_almazny(almazny)
            print("SR outputs are OFF. Press ENTER when done.")
            self.legacy_almazny_toggle_output(almazny, False)
            input()
            print("RF ON, attenuators are tested. Press ENTER when done.")
            self.legacy_almazny_toggle_output(almazny, True)
            self.legacy_almazny_att_test(almazny)
            self.legacy_almazny_toggle_output(almazny, False)

    @kernel
    def almazny_led_wave(self, almaznys):
        while not is_enter_pressed():
            self.core.break_realtime()
            # do not fill the FIFOs too much to avoid long response times
            t = now_mu() - self.core.seconds_to_mu(0.2)
            while self.core.get_rtio_counter_mu() < t:
                pass
            for ch in almaznys:
                ch.set(31.5, False, True)
                delay(100 * ms)
                ch.set(31.5, False, False)

    @kernel
    def almazny_att_test(self, almaznys):
        rf_en = 1
        led = 1
        att_mu = 0
        while not is_enter_pressed():
            self.core.break_realtime()
            t = now_mu() - self.core.seconds_to_mu(0.2)
            while self.core.get_rtio_counter_mu() < t:
                pass
            setting = led << 7 | rf_en << 6 | (att_mu & 0x3F)
            for ch in almaznys:
                ch.set_mu(setting)
            delay(250 * ms)
            if att_mu == 0:
                att_mu = 1
            else:
                att_mu = (att_mu << 1) & 0x3F

    def test_almaznys(self):
        print("*** Testing Almaznys (v1.2+).")
        print("Initializing Mirny CPLDs...")
        for name, cpld in sorted(self.mirny_cplds.items(), key=lambda x: x[0]):
            print(name + "...")
            self.init_mirny(cpld)
        print("...done")
        print("Frequencies:")
        for card_n, channels in enumerate(chunker(self.mirnies, 4)):
            for channel_n, (channel_name, channel_dev) in enumerate(channels):
                frequency = 75 + card_n * 10 + channel_n * 1
                print("Almazny freq: {}\t{}MHz".format(channel_name, frequency * 2))
                self.setup_mirny(channel_dev, frequency)
        print("RF ON, attenuators are tested. Press ENTER when done.")
        self.almazny_att_test([ch for _, ch in self.almaznys.items()])
        print("RF OFF, testing LEDs. Press ENTER when done.")
        self.almazny_led_wave([ch for _, ch in self.almaznys.items()])

    def test_mirnies(self):
        print("*** Testing Mirny PLLs.")

        print("Initializing CPLDs...")
        for name, cpld in sorted(self.mirny_cplds.items(), key=lambda x: x[0]):
            print(name + "...")
            self.init_mirny(cpld)
        print("...done")

        print("All mirny channels active.")
        print("Frequencies:")
        for card_n, channels in enumerate(chunker(self.mirnies, 4)):
            for channel_n, (channel_name, channel_dev) in enumerate(channels):
                frequency = 100 + 10 * (card_n + 1) + channel_n * 1
                print("Mirny freq: {}\t{}MHz".format(channel_name, frequency))
                self.setup_mirny(channel_dev, frequency)
                print("{} info: {}".format(channel_name, channel_dev.info()))
        print("Press ENTER when done.")
        input()

        sw = [
            channel_dev
            for channel_name, channel_dev in self.mirnies
            if hasattr(channel_dev, "sw")
        ]
        if sw:
            print("Testing RF switch control. Check LEDs at mirny RF ports.")
            print("Press ENTER when done.")
            for swi in sw:
                self.sw_off_mirny(swi)
            self.mirny_rf_switch_wave([swi.sw for swi in sw])

    def run(self):
        print("****** Mirny/Almazny tester ******")
        print("")
        self.core.reset()

        self.test_mirnies()

        self.test_almaznys()

        self.test_legacy_almaznys()

def main():
    device_mgr = DeviceManager(DeviceDB("device_db.py"))
    try:
        experiment = MirnyTester((device_mgr, None, None, None))
        experiment.prepare()
        experiment.run()
        experiment.analyze()
    finally:
        device_mgr.close_devices()


if __name__ == "__main__":
    main()
