"""
We steal some of the functionality from artiq_client into a gui
This is designed to be used alongside the dashboard

    - Monitor device state via datasets
        + BoosterTelemetry subscription
        + DLCPro???

    - Control devices by submitting experiment fragments for them

    - The Idle kernel will set the device state to the database state between experiments


This is achieved by running a Subscriber in the background that listens for changes to the datasets
widgets can register to be updated for specific datasets

Devices:
    - 780 MOT
        + AOM (Freq/Amplitude/Booster)
        + EOM 
        + Shutter

    - Imaging
        + Shutter

    - Repump
        + Shutter

    - 852 
        + AOM (Freq/Amplitude/Booster) - for (X, Y)
        + Shutter

    - 1064 
        + AOM (Freq/Amplitude/Booster) - for (1, 2)

    - Coils
        + Current (X+, X-, Y, Z)

    - PCO Camera
        + Exposure
        + Trigger

    - Wavemeter

"""

from sipyco.sync_struct import Subscriber
from sipyco.asyncio_tools import SignalHandler
import asyncio

from PyQt6.QtCore import QObject, QThread

from utils.boosterTelemetry import BoosterTelemetry

datasets = dict()
port = 3250
server = "137.222.69.28"


class Client:
    # Holds the connection to everything we want to monitor
    # Artiq, Booster, DLCPro, etc

    def __init__(self):
        self.booster_init()
        self.artiq_init()

    def artiq_init(self):
        self.datasets = dict()

        def init_d(x):
            self.datasets.clear()
            self.datasets.update(x)
            return self.datasets

        subscriber = Subscriber(
            "datasets", init_d, lambda mod: self.artiq_callback(self.datasets)
        )
        _run_subscriber(server, port, subscriber)

    def artiq_callback(self, data):
        datasets.update(data)
        print("\nnew Artiq data:\n", data)

    def booster_init(self):
        self.booster = BoosterTelemetry(self.booster_callback)
        self.booster_state = dict()
        self.booster_callbacks = [[]] * 8

        self.booster.start()

        # # start the booster in the background
        # self.booster_thread = QThread()
        # self.booster.moveToThread(self.booster_thread)
        # self.booster_thread.start()

    def booster_callback(self, ch, data):
        self.booster_state[ch] = data
        print("\nnew Booster data:\n", data)
        for cb in self.booster_callbacks[ch]:
            cb(data)

    def register_booster_callback(self, ch, cb):
        self.booster_callbacks[ch].append(cb)


def _run_subscriber(host, port, subscriber):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        signal_handler = SignalHandler()
        signal_handler.setup()
        try:
            loop.run_until_complete(subscriber.connect(host, port))
            try:
                _, pending = loop.run_until_complete(
                    asyncio.wait(
                        [
                            loop.create_task(signal_handler.wait_terminate()),
                            subscriber.receive_task,
                        ],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                )
                for task in pending:
                    task.cancel()
            finally:
                loop.run_until_complete(subscriber.close())
        finally:
            signal_handler.teardown()
    finally:
        loop.close()


if __name__ == "__main__":
    client = Client()
    print("done")