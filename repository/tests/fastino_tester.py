#!/usr/bin/env python3
import sys

sys.path.append(
    __file__.split("repository")[0] + "repository"
)  # link to repository root

from artiq.experiment import *
from artiq.master.databases import DeviceDB
from artiq.master.worker_db import DeviceManager

from artiq.coredevice.core import Core
from utils.surpress_missing_imports import *
from utils.wait_for_enter import is_enter_pressed


class FastinoTester(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core

        self.fastinos = dict()

        ddb = self.get_device_db()
        for name, desc in ddb.items():
            if isinstance(desc, dict) and desc["type"] == "local":
                module, cls = desc["module"], desc["class"]
                if (module, cls) == ("artiq.coredevice.fastino", "Fastino"):
                    self.fastinos[name] = self.get_device(name)

        self.fastinos = sorted(self.fastinos.items())

    @kernel
    def set_fastino_voltages(self, fastino, voltages):
        self.core.break_realtime()
        fastino.init()
        delay(200 * us)
        i = 0
        for voltage in voltages:
            fastino.set_dac(i, voltage)
            delay(100 * us)
            i += 1

    @kernel
    def fastinos_led_wave(self, fastinos):
        while not is_enter_pressed():
            self.core.break_realtime()
            # do not fill the FIFOs too much to avoid long response times
            t = now_mu() - self.core.seconds_to_mu(0.2)
            while self.core.get_rtio_counter_mu() < t:
                pass
            for fastino in fastinos:
                for i in range(8):
                    fastino.set_leds(1 << i)
                    delay(100 * ms)
                fastino.set_leds(0)
                delay(100 * ms)

    def test_fastinos(self):
        print("*** Testing Fastino DACs and USER LEDs.")
        print("Voltages:")
        for card_n, (card_name, card_dev) in enumerate(self.fastinos):
            voltages = [
                (-1) ** i * (2.0 * card_n + 1.1 * (i // 4 + 1)) for i in range(32)
            ]
            print(card_name, " ".join(["{:.1f}".format(x) for x in voltages]))
            self.set_fastino_voltages(card_dev, voltages)
        print("Press ENTER when done.")
        # Test switching on/off USR_LEDs at the same time
        self.fastinos_led_wave(
            [card_dev for _, (__, card_dev) in enumerate(self.fastinos)]
        )

    def run(self):
        print("****** Fastino tester ******")
        print("")
        self.core.reset()

        self.test_fastinos()


def main():
    device_mgr = DeviceManager(DeviceDB("device_db.py"))
    try:
        experiment = FastinoTester((device_mgr, None, None, None))
        experiment.prepare()
        experiment.run()
        experiment.analyze()
    finally:
        device_mgr.close_devices()


if __name__ == "__main__":
    main()
