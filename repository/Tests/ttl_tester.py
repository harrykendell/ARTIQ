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


class TTLTester(EnvExperiment):
    def build(self):
        self.setattr_device("core")

        self.leds = dict()
        self.ttl_outs = dict()
        self.ttl_ins = dict()

        ddb = self.get_device_db()
        for name, desc in ddb.items():
            if isinstance(desc, dict) and desc["type"] == "local":
                module, cls = desc["module"], desc["class"]
                if (module, cls) == ("artiq.coredevice.ttl", "TTLOut"):
                    dev = self.get_device(name)
                    if "led" in name:  # guess
                        self.leds[name] = dev
                    else:
                        self.ttl_outs[name] = dev
                elif (module, cls) == ("artiq.coredevice.ttl", "TTLInOut"):
                    self.ttl_ins[name] = self.get_device(name)

        # Sort everything by RTIO channel number
        self.leds = sorted(self.leds.items())
        self.ttl_outs = sorted(self.ttl_outs.items())
        self.ttl_ins = sorted(self.ttl_ins.items())

    @kernel
    def test_led(self, led):
        while not is_enter_pressed():
            self.core.break_realtime()
            # do not fill the FIFOs too much to avoid long response times
            t = now_mu() - self.core.seconds_to_mu(0.2)
            while self.core.get_rtio_counter_mu() < t:
                pass
            for i in range(3):
                led.pulse(100 * ms)
                delay(100 * ms)

    def test_leds(self):
        print("*** Testing LEDs.")
        print("Check for blinking. Press ENTER when done.")

        for led_name, led_dev in self.leds:
            print("Testing LED: {}".format(led_name))
            self.test_led(led_dev)

    @kernel
    def test_ttl_out_chunk(self, ttl_chunk):
        self.core.break_realtime()

        for ttl in ttl_chunk:
            ttl.output()
        delay(100 * ms)
        while not is_enter_pressed():
            self.core.break_realtime()
            for _ in range(50000):
                i = 0
                for ttl in ttl_chunk:
                    i += 1
                    for _ in range(i):
                        ttl.pulse(1 * us)
                        delay(1 * us)
                    delay(10 * us)

    def test_ttl_outs(self):
        print("*** Testing TTL outputs.")
        print("Outputs are tested in groups of 4. Touch each TTL connector")
        print("with the oscilloscope probe tip, and check that the number of")
        print("pulses corresponds to its number in the group.")
        print("Press ENTER when done.")

        for ttl_chunk in chunker(self.ttl_outs, 4):
            print(
                "Testing TTL outputs: {}.".format(
                    ", ".join(name for name, dev in ttl_chunk)
                )
            )
            self.test_ttl_out_chunk([dev for name, dev in ttl_chunk])

    @kernel
    def test_ttl_in(self, ttl_out, ttl_in):
        n = 42
        self.core.break_realtime()
        with parallel:
            ttl_in.gate_rising(1 * ms)
            with sequential:
                delay(50 * us)
                for _ in range(n):
                    ttl_out.pulse(2 * us)
                    delay(2 * us)
        return ttl_in.count(now_mu()) == n

    def test_ttl_ins(self):
        print("*** Testing TTL inputs.")
        if not self.ttl_outs:
            print("No TTL output channel available to use as stimulus.")
            return
        default_ttl_out_name, default_ttl_out_dev = next(iter(self.ttl_outs))
        ttl_out_name = input(
            "TTL device to use as stimulus (default: {}): ".format(default_ttl_out_name)
        )
        if ttl_out_name:
            ttl_out_dev = self.get_device(ttl_out_name)
        else:
            ttl_out_name = default_ttl_out_name
            ttl_out_dev = default_ttl_out_dev
        for ttl_in_name, ttl_in_dev in self.ttl_ins:
            print(
                "Connect {} to {}. Press ENTER when done.".format(
                    ttl_out_name, ttl_in_name
                )
            )
            input()
            if self.test_ttl_in(ttl_out_dev, ttl_in_dev):
                print("PASSED")
            else:
                print("FAILED")

    def run(self):
        print("****** TTL tester ******")
        print("")
        self.core.reset()

        self.test_leds()

        self.test_ttl_outs()

        self.test_ttl_ins()


def main():
    device_mgr = DeviceManager(DeviceDB("device_db.py"))
    try:
        experiment = TTLTester((device_mgr, None, None, None))
        experiment.prepare()
        experiment.run()
        experiment.analyze()
    finally:
        device_mgr.close_devices()


if __name__ == "__main__":
    main()
