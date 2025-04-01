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

import sys
import logging
import numpy as np

# Data subscriptions
from sipyco.pc_rpc import AsyncioClient
from sipyco.sync_struct import Subscriber
import asyncio
from qasync import QEventLoop
import aiomqtt

from artiq.master.scheduler import Scheduler

# GUI
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
)

# include the artiq path by slicing our current path to the root
sys.path.append(__file__.split("artiq")[0] + "artiq")
from repository.gui.components.ScientificSpin import ScientificSpin  # noqa


class GUIClient:
    def __init__(self, server="137.222.69.28", port_control=3251, port_notify=3250):
        self.server = server
        self.port_control = port_control
        self.port_notify = port_notify

        self.rpc_clients: dict[AsyncioClient] = {}
        self.subscribers: dict[Subscriber] = {}

        for subscriber in ["dataset", "explist", "schedule", "dlcpro", "booster"]:
            self.__dict__[f"{subscriber}"] = dict()
            self.__dict__[f"{subscriber}_callbacks"] = []

    async def connect(self):
        """Initialize connections."""
        loop = asyncio.get_event_loop()

        # Connect RPC clients
        for target in ["dataset_db", "schedule"]:
            loop.create_task(self.connect_rpc(target))

        # Connect subscribers
        for name, db, callbacks, port in [
            ("datasets", self.dataset, self.dataset_callbacks, self.port_notify),
            ("explist", self.explist, self.explist_callbacks, self.port_notify),
            ("schedule", self.schedule, self.schedule_callbacks, self.port_notify),
            ("DLCProState", self.dlcpro, self.dlcpro_callbacks, 3271),
        ]:
            loop.create_task(self.connect_subscriber(name, db, callbacks, port))

        loop.create_task(self.connect_booster())

        logging.info("Connecting to services...")

    async def connect_subscriber(self, name, db, callbacks, port=None, server=None):
        port = self.port_notify if port is None else port
        server = self.server if server is None else server

        def _create(data):
            logging.debug(f"New {name}")
            db.update(data)
            return db

        def _update(mod):
            logging.debug(f"New {name} mod")
            for cb in callbacks:
                cb()
            return

        subscriber = Subscriber(name, _create, _update, None)
        try:
            await asyncio.wait_for(
                subscriber.connect(
                    server,
                    port,
                ),
                5,
            )
        except asyncio.TimeoutError:
            logging.error(f"Failed to connect to Sub: {name} at {server}:{port}")
            return
        self.subscribers[name] = subscriber
        logging.info(f"Connected to Sub: {name} at {server}:{port}")

    async def connect_rpc(self, target, server=None, port=None):
        server = self.server if server is None else server
        port = self.port_control if port is None else port
        client = AsyncioClient()
        try:
            await asyncio.wait_for(
                client.connect_rpc(
                    server,
                    port,
                    target,
                ),
                5,
            )
        except asyncio.TimeoutError:
            logging.error(f"Failed to connect to RPC: {target} at {server}:{port}")
            return
        self.rpc_clients[target] = client
        logging.info(f"Connected to RPC: {target} at {server}:{port}")

    async def connect_booster(self):
        """Initialize MQTT connection for booster telemetry."""

        # Define the callback for handling incoming MQTT messages
        def handle_booster_message(message):
            """Handle the incoming telemetry message."""
            logging.debug(f"New Booster message: {message.payload.decode()}")
            ch = int(message.topic.value[-1])
            data = message.payload.decode()
            self.booster[ch] = data

            # Call any registered callback for this channel
            for cb in self.booster_callbacks:
                logging.debug(f"Calling booster callback {cb} with {data}")
                cb()

        # MQTT connection and subscription
        try:
            async with aiomqtt.Client(self.server) as client:
                # Subscribe to booster telemetry channels 0-7
                await asyncio.wait_for(
                    client.subscribe("dt/sinara/booster/fc-0f-e7-23-77-30/telemetry/#"),
                    5,
                )

                client._on_message = (
                    handle_booster_message  # Assign callback for messages
                )
                async for message in client.messages:
                    handle_booster_message(
                        message
                    )  # Pass each incoming message to the handler
        except aiomqtt.exceptions.MqttError or asyncio.TimeoutError as e:
            logging.error(f"Failed to connect to Booster:\n{e}")
            return
        logging.info("Connected to Booster")

    def register_callback(self, target, cb):
        # register a callback for booster, dataset, dlcpro, schedule, or
        self.__dict__[f"{target}_callbacks"].append(cb)
        cb()

    async def _submit_by_content(self, content, exp_class_name, title):
        scheduler: Scheduler = self.rpc_clients["schedule"]
        expid = {
            "log_level": logging.WARNING,
            "content": content,
            "class_name": exp_class_name,
            "arguments": {},
        }
        scheduling = {
            "pipeline_name": "main",
            "priority": 0,
            "due_date": None,
            "flush": False,
        }
        rid = await scheduler.submit(
            scheduling["pipeline_name"],
            expid,
            scheduling["priority"],
            scheduling["due_date"],
            scheduling["flush"],
        )
        logging.info("Submitted '%s', RID is %d", title, rid)

    async def disconnect(self):
        """Disconnect all connections."""
        for client in self.rpc_clients.values():
            await client.close_rpc()
        for subscriber in self.subscribers.values():
            await subscriber.close()
        logging.info("Disconnected from all connections.")


class MainWindow(QWidget):
    def __init__(self, client: GUIClient):
        super().__init__()

        self.client = client

        self.setWindowTitle("ARTIQ GUI")
        self.setGeometry(100, 100, 800, 600)

        self.inutUI()

        self.register_callbacks()

    def inutUI(self):
        layout = QVBoxLayout()

        self.spinbox = ScientificSpin()
        layout.addWidget(self.spinbox)

        for name, fn in [
            ("dataset", self.update_dataset),
            ("explist", self.update_explist),
            ("schedule", self.update_schedule),
            ("dlcpro", self.update_dlcpro),
            ("booster", self.update_booster),
        ]:
            label = QLabel(f"{name}::")
            self.__dict__[f"{name}_text"] = QTextEdit()
            self.__dict__[f"{name}_text"].setReadOnly(True)
            layout.addWidget(label)
            layout.addWidget(self.__dict__[f"{name}_text"])
            fn()

            if name == "dataset":
                layout.addWidget(QLabel("Save"))
                save_button = QPushButton("Save")
                save_button.clicked.connect(self.saveDataset)
                layout.addWidget(save_button)

        self.layout = layout
        self.setLayout(self.layout)

    def update_dataset(self):
        text = ""
        for key, value in self.client.dataset.items():
            text += f"{key}\n\t{value}\n"
        self.dataset_text.setText(text)

    def update_explist(self):
        text = ""
        for key in self.client.explist.keys():
            text += f"{key}\n"
        self.explist_text.setText(text)

    def update_schedule(self):
        text = ""
        for key, value in self.client.schedule.items():
            text += f"<b>{value['status']}</b>\t{value['expid']['class_name']}\n"
        self.schedule_text.setText(text)

    def update_dlcpro(self):
        self.dlcpro_text.setText(str(self.client.dlcpro))

    def update_booster(self):
        self.booster_text.setText(str(self.client.booster))

    def register_callbacks(self):
        for target in ["dataset", "explist", "schedule", "dlcpro", "booster"]:
            self.client.register_callback(target, getattr(self, f"update_{target}"))

    def saveDataset(self):
        data = {key: val[1] for key, val in self.client.dataset.items()}
        print("Saving dataset, type: ", type(data))
        np.save("dataset.npy", data)


def main():
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    server = "137.222.69.28"

    client = GUIClient(server)
    main_window = MainWindow(client)

    app.aboutToQuit.connect(lambda: loop.create_task(client.disconnect()))

    # Start connections
    loop.create_task(client.connect())

    main_window.show()
    loop.run_forever()


if __name__ == "__main__":
    main()
