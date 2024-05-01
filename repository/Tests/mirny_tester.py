#!/usr/bin/env python3
import sys, os

sys.path.append(
    os.path.join(os.path.dirname(__file__), "..")
)  # link to repository root

from artiq.experiment import *
from artiq.master.databases import DeviceDB
from artiq.master.worker_db import DeviceManager

from utils.surpress_missing_imports import *
from utils.wait_for_enter import is_enter_pressed


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

        self.mirny_cplds = dict()
        self.mirnies = dict()
        self.almaznys = dict()

        ddb = self.get_device_db()
        for name, desc in ddb.items():
            if isinstance(desc, dict) and desc["type"] == "local":
                module, cls = desc["module"], desc["class"]
                if (module, cls) == ("artiq.coredevice.mirny", "Mirny"):
                    self.mirny_cplds[name] = self.get_device(name)
                elif (module, cls) == ("artiq.coredevice.adf5356", "ADF5356"):
                    self.mirnies[name] = self.get_device(name)
                elif (module, cls) == ("artiq.coredevice.mirny", "Almazny"):
                    self.almaznys[name] = self.get_device(name)

        # Sort everything by RTIO channel number
        self.mirnies = sorted(self.mirnies.items())

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

    @kernel
    def init_almazny(self, almazny):
        self.core.break_realtime()
        almazny.init()
        almazny.output_toggle(True)

    @kernel
    def almazny_set_attenuators_mu(self, almazny, ch, atts):
        self.core.break_realtime()
        almazny.set_att_mu(ch, atts)

    @kernel
    def almazny_set_attenuators(self, almazny, ch, atts):
        self.core.break_realtime()
        almazny.set_att(ch, atts)

    @kernel
    def almazny_toggle_output(self, almazny, rf_on):
        self.core.break_realtime()
        almazny.output_toggle(rf_on)

    def test_almaznys(self):
        print("*** Testing Almaznys.")
        for name, almazny in sorted(self.almaznys.items(), key=lambda x: x[0]):
            print(name + "...")
            print("Initializing Mirny CPLDs...")
            for name, cpld in sorted(self.mirny_cplds.items(), key=lambda x: x[0]):
                print(name + "...")
                self.init_mirny(cpld)
            print("...done")

            print("Testing attenuators. Frequencies:")
            for card_n, channels in enumerate(chunker(self.mirnies, 4)):
                for channel_n, (channel_name, channel_dev) in enumerate(channels):
                    frequency = 2000 + card_n * 250 + channel_n * 50
                    frequency = 55 + card_n * 5 + channel_n * 2.5
                    print("{}\t{}MHz".format(channel_name, frequency * 2))
                    self.setup_mirny(channel_dev, frequency)
                    print("{} info: {}".format(channel_name, channel_dev.info()))
            self.init_almazny(almazny)
            print("RF ON, all attenuators ON. Press ENTER when done.")
            for i in range(4):
                self.almazny_set_attenuators_mu(almazny, i, 63)
            input()
            print("RF ON, half power attenuators ON. Press ENTER when done.")
            for i in range(4):
                self.almazny_set_attenuators(almazny, i, 15.5)
            input()
            print("RF ON, all attenuators OFF. Press ENTER when done.")
            for i in range(4):
                self.almazny_set_attenuators(almazny, i, 0)
            input()
            print("SR outputs are OFF. Press ENTER when done.")
            self.almazny_toggle_output(almazny, False)
            input()
            print("RF ON, all attenuators are ON. Press ENTER when done.")
            for i in range(4):
                self.almazny_set_attenuators(almazny, i, 31.5)
            self.almazny_toggle_output(almazny, True)
            input()
            print("RF OFF. Press ENTER when done.")
            self.almazny_toggle_output(almazny, False)
            input()

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
                frequency = 1000 * (card_n + 1) + channel_n * 100
                frequency = 55 * (card_n + 1) + channel_n * 2.5
                print("{}\t{}MHz".format(channel_name, frequency))
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
