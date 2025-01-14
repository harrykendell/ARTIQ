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
from sipyco.pc_rpc import AsyncioClient
from sipyco.sync_struct import Subscriber, process_mod
from sipyco.asyncio_tools import atexit_register_coroutine, atexit
import asyncio
from qasync import QEventLoop
from artiq.dashboard import datasets, schedule
from artiq.gui.models import ModelSubscriber
from utils.boosterTelemetry import BoosterTelemetry

from PyQt5.QtWidgets import QApplication, QLabel
from PyQt5.QtGui import QIcon


class Client:
    # Holds the connection to everything we want to monitor
    # Artiq, Booster, DLCPro, etc

    def __init__(self, loop: QEventLoop):
        self.server = "137.222.69.28"
        self.port_control = 3251
        self.port_notify = 3250
        self.loop = loop
        self.booster_init()
        self.artiq_init()

    def artiq_init(self):
        # create connections to master
        rpc_clients = dict()
        for target in "schedule", "dataset_db":
            client = AsyncioClient()
            self.loop.run_until_complete(client.connect_rpc(
                self.server, self.port_control, target))
            atexit.register(client.close_rpc)
            rpc_clients[target] = client

        def create_dict(x):
            d = dict()
            d.update(x)
            print(d)
            return d
        
        def modify_d(x):
            print("New database mod:\n", x)
            return
        
        def modify_s(x):
            print("New schedule:\n", x)
            return
        
        sub_clients = dict()
        for notifier_name, modify in (("datasets", modify_d),("schedule", modify_s)):
            subscriber = Subscriber(notifier_name, target_builder=create_dict, notify_cb=modify, disconnect_cb=None)
            self.loop.run_until_complete(subscriber.connect(
                self.server, self.port_notify))
            atexit_register_coroutine(subscriber.close, loop=self.loop)
            sub_clients[notifier_name] = subscriber


    def data_callback(self, model: datasets.Model):
        print("New model:\n", model.backing_store)

    def booster_init(self):
        self.booster = BoosterTelemetry(self.booster_callback)
        self.booster_state = dict()
        self.booster_callbacks = [[]] * 8
        self.booster.start()

    def booster_callback(self, ch, data):
        self.booster_state[ch] = data
        print("\nnew Booster data:\n", data)
        for cb in self.booster_callbacks[ch]:
            cb(data)

    def register_booster_callback(self, ch, cb):
        self.booster_callbacks[ch].append(cb)


def main():
    app = QApplication(["Test GUI"])

    loop = QEventLoop(app)
    # loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    atexit.register(loop.close)

    client = Client(loop)
    # Set a nice icon
    app.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/do.png"))
    app.setStyle("Fusion")
    app.setApplicationName("ARTIQ GUI")

    screen = QLabel("Hello, World!")
    screen.show()

    app.exec()


if __name__ == "__main__":
    main()
