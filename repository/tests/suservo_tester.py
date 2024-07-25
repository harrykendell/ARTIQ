#!/usr/bin/env python3
import sys

sys.path.append(
    __file__.split("repository")[0] + "repository"
)  # link to repository root

from artiq.experiment import *
from artiq.master.databases import DeviceDB
from artiq.master.worker_db import DeviceManager

from artiq.coredevice.suservo import SUServo, Channel
from artiq.coredevice.core import Core

from utils.surpress_missing_imports import *


def chunker(seq, size):
    res = []
    for el in seq:
        res.append(el)
        if len(res) == size:
            yield res
            res = []
    if res:
        yield res


class SUServoTester(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.core: Core
        self.suservos = dict()
        self.suschannels = dict()

        ddb = self.get_device_db()
        for name, desc in ddb.items():
            if isinstance(desc, dict) and desc["type"] == "local":
                module, cls = desc["module"], desc["class"]
                if (module, cls) == ("artiq.coredevice.suservo", "SUServo"):
                    self.suservos[name] = self.get_device(name)
                elif (module, cls) == ("artiq.coredevice.suservo", "Channel"):
                    self.suschannels[name] = self.get_device(name)

        self.suservos: list[SUServo] = sorted(self.suservos.items())
        self.suschannels: list[Channel] = sorted(self.suschannels.items())

    @kernel
    def setup_suservo(self, channel: SUServo):
        self.core.break_realtime()
        channel.init()
        delay(1 * us)
        # ADC PGIA gain 0
        for i in range(8):
            channel.set_pgia_mu(i, 0)
            delay(10 * us)
        # DDS attenuator 10dB
        for i in range(4):
            for cpld in channel.cplds:
                cpld.set_att(i, 10.0)
        delay(1 * us)
        # Servo is done and disabled
        assert channel.get_status() & 0xFF == 2
        delay(10 * us)

    @kernel
    def setup_suservo_loop(self, channel: Channel, loop_nr):
        self.core.break_realtime()
        channel.set_y(profile=loop_nr, y=0.0)  # clear integrator
        channel.set_iir(
            profile=loop_nr,
            adc=loop_nr,  # take data from Sampler channel
            kp=-1.0,  # -1 P gain
            ki=0.0 / s,  # no integrator gain
            g=0.0,  # no integrator gain limit
            delay=0.0,  # no IIR update delay after enabling
        )
        # setpoint 0.5 (5 V with above PGIA gain setting)
        delay(100 * us)
        channel.set_dds(
            profile=loop_nr,
            offset=-0.3,  # 3 V with above PGIA settings
            frequency=10 * MHz,
            phase=0.0,
        )
        # enable RF, IIR updates and set profile
        delay(10 * us)
        channel.set(en_out=1, en_iir=1, profile=loop_nr)

    @kernel
    def setup_start_suservo(self, channel: SUServo):
        self.core.break_realtime()
        channel.set_config(enable=1)
        delay(10 * us)
        # check servo enabled
        assert channel.get_status() & 0x01 == 1
        delay(10 * us)

    def test_suservos(self):
        print("*** Testing SUServos.")
        print("Initializing modules...")
        for card_name, card_dev in self.suservos:
            print(card_name)
            self.setup_suservo(card_dev)
        print("...done")
        print("Setting up SUServo channels...")
        for channels in chunker(self.suschannels, 8):
            for i, (channel_name, channel_dev) in enumerate(channels):
                print(channel_name)
                self.setup_suservo_loop(channel_dev, i)
        print("...done")
        print("Enabling...")
        for card_name, card_dev in self.suservos:
            print(card_name)
            self.setup_start_suservo(card_dev)
        print("...done")
        print("Each Sampler channel applies proportional amplitude control")
        print("on the respective Urukul0 (ADC 0-3) and Urukul1 (ADC 4-7, if")
        print("present) channels.")
        print(
            "Frequency: 10 MHz, output power: about -9 dBm at 0 V and about -15 dBm at 1.5 V"
        )
        print("Verify frequency and power behavior.")
        print("Press ENTER when done.")
        input()

    def run(self):
        print("****** SUServo tester ******")
        print("")
        self.core.reset()

        self.test_suservos()


def main():
    device_mgr = DeviceManager(DeviceDB("device_db.py"))
    try:
        experiment = SUServoTester((device_mgr, None, None, None))
        experiment.prepare()
        experiment.run()
        experiment.analyze()
    finally:
        device_mgr.close_devices()


if __name__ == "__main__":
    main()
