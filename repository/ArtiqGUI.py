"""
We steal some of the functionality from artiq_client into a gui
This is designed to be used alongside the dashboard

    - Monitor device state via datasets
        + The Idle kernel keeps reading out values into datasets e.g. sampler values
        + BoosterTelemetry subscription
        + DLCPro???

    - Control devices by submitting experiment fragments for them

    - The Idle kernel will set the device state to the database state between experiments


This is achieved by running a Subscriber in the background that listens for changes to the datasets
widgets can register to be updated for specific datasets
"""

import sys, logging

# Data subscriptions
from sipyco.pc_rpc import AsyncioClient
from sipyco.sync_struct import Subscriber
from sipyco.asyncio_tools import atexit_register_coroutine, atexit
import asyncio
from qasync import QEventLoop
from utils.boosterTelemetry import BoosterTelemetry

# GUI
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QTextEdit
from PyQt5.QtGui import QIcon
from artiq.gui.scientific_spinbox import ScientificSpinBox


class Client:
    # Holds the connection to everything we want to monitor
    # Artiq, Booster, DLCPro, etc

    def __init__(
        self,
        app: QApplication,
        server="137.222.69.28",
        port_control=3251,
        port_notify=3250,
    ):
        self.server = server
        self.port_control = port_control
        self.port_notify = port_notify

        self.loop = QEventLoop(app)
        asyncio.set_event_loop(self.loop)
        atexit.register(self.loop.close)

        self.booster_db = dict()

        self.rpc_clients: dict[AsyncioClient] = dict()
        self.sub_clients: dict[Subscriber] = dict()

        self.schedule_db = dict()
        self.datatset_db = dict()

    # manage connections with context manager
    def __enter__(self):
        self.booster_init()
        self.rpc_init()
        self.schedule_init()
        self.dataset_init()

        return self

    def __exit__(self, exc_type, exc_value, traceback):
        for client in self.rpc_clients.values():
            client: AsyncioClient
            client.close_rpc()
        for client in self.sub_clients.values():
            client: Subscriber
            client.close()

    def rpc_init(self):
        # create connections to master
        for target in "schedule", "dataset_db":
            client = AsyncioClient()
            self.loop.run_until_complete(
                client.connect_rpc(self.server, self.port_control, target)
            )
            self.rpc_clients[target] = client

    def dataset_init(self):
        self.dataset_callbacks = dict()

        def create_d(data):
            self.datatset_db = data
            logger.debug(f"New dataset:\n{self.datatset_db}")
            return self.datatset_db

        def modify_d(mod):

            if mod["action"] != "setitem":
                if mod["action"] == "init":
                    for key in self.dataset_callbacks.keys():
                        [cb() for cb in self.dataset_callbacks[key]]
                else:
                    logging.error(f"We cannot handle {mod['action']} on datasets")
                return

            logging.debug(f"New dataset mod")
            # we want to trigger on the key or a subpath of the key
            # i.e. if we have a key "foo" we want to trigger on mod["key"] = "foo"/"foo.bar" but not "foobar"
            # also * should trigger on everything
            for key in self.dataset_callbacks.keys():
                if key == mod["key"] or mod["key"].startswith(key + ".") or key == "*":
                    [cb() for cb in self.dataset_callbacks[key]]
            return

        subscriber = Subscriber(
            "datasets",
            target_builder=create_d,
            notify_cb=modify_d,
            disconnect_cb=None,
        )
        self.loop.run_until_complete(subscriber.connect(self.server, self.port_notify))
        self.sub_clients["datasets"] = subscriber

    def schedule_init(self):
        self.schedule_callbacks = []

        def create_s(data):
            self.schedule_db = data
            return self.schedule_db

        def modify_s(mod):
            logging.debug(f"New schedule mod")
            [cb() for cb in self.schedule_callbacks]
            return

        subscriber = Subscriber(
            "schedule",
            target_builder=create_s,
            notify_cb=modify_s,
            disconnect_cb=None,
        )
        self.loop.run_until_complete(subscriber.connect(self.server, self.port_notify))
        atexit_register_coroutine(subscriber.close, loop=self.loop)
        self.sub_clients["schedule"] = subscriber

    # register to be called when new data is available
    # cb()
    def register_dataset_callback(self, key, cb):
        if key not in self.dataset_callbacks:
            self.dataset_callbacks[key] = []
        self.dataset_callbacks[key].append(cb)
        cb()

    # register to be called when new data is available
    # cb()
    def register_schedule_callback(self, cb):
        self.schedule_callbacks.append(cb)
        cb()

    def booster_init(self):
        def booster_callback(ch, data):
            logging.debug(f"\nnew Booster data ({ch}):\n{data}")
            self.booster_db[ch] = data
            for cb in self.booster_callbacks[ch]:
                cb()

        self.booster = BoosterTelemetry(booster_callback)
        self.booster_callbacks = [[]] * 8
        self.booster.start()
        self.booster.set_telem_period(5)

    # register to be called when new data is available
    # cb()
    def register_booster_callback(self, ch, cb):
        if ch == "*":
            [self.booster_callbacks[i].append(cb) for i in range(8)]
        elif ch in range(8):
            self.booster_callbacks[ch].append(cb)
        else:
            logging.error(f"Invalid booster channel {ch}")


class UI(QWidget):
    def __init__(self, client: Client):
        super().__init__()

        self.client = client

        self.setWindowTitle("ARTIQ GUI")
        self.setGeometry(100, 100, 800, 600)

        self.inutUI()

        self.register_callbacks()

    def inutUI(self):
        layout = QVBoxLayout()

        self.spinbox = ScientificSpinBox()
        layout.addWidget(self.spinbox)

        self.dataset_label = QLabel("Dataset:")
        self.dataset_text = QTextEdit()
        self.dataset_text.setReadOnly(True)
        layout.addWidget(self.dataset_label)
        layout.addWidget(self.dataset_text)
        self.update_dataset()

        self.schedule_label = QLabel("Schedule:")
        self.schedule_text = QTextEdit()
        self.schedule_text.setReadOnly(True)
        layout.addWidget(self.schedule_label)
        layout.addWidget(self.schedule_text)
        self.update_schedule()

        self.booster_label = QLabel("Booster:")
        self.booster_text = QTextEdit()
        self.booster_text.setReadOnly(True)
        layout.addWidget(self.booster_label)
        layout.addWidget(self.booster_text)
        self.update_booster()

        self.setLayout(layout)

    def update_dataset(self):
        self.dataset_text.setText(str(self.client.datatset_db))

    def update_schedule(self):
        self.schedule_text.setText(str(self.client.schedule_db))

    def update_booster(self):
        self.booster_text.setText(str(self.client.booster_db))

    def register_callbacks(self):
        self.client.register_dataset_callback("*", self.update_dataset)
        self.client.register_schedule_callback(self.update_schedule)
        self.client.register_booster_callback("*", self.update_booster)


def main():
    app = QApplication(["Test GUI"])
    # Set a nice icon
    app.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/do.png"))
    app.setStyle("Fusion")
    app.setApplicationName("ARTIQ GUI")

    with Client(app) as client:

        ui = UI(client)
        ui.show()

        sys.exit(app.exec())


if __name__ == "__main__":
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    main()
