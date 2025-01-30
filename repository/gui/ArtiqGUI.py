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

from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from PyQt5 import QtCore

# Data subscriptions
from sipyco.pc_rpc import AsyncioClient
from sipyco.sync_struct import Subscriber
import asyncio
from qasync import QEventLoop
import aiomqtt

# GUI
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QTextEdit

# include the artiq path by slicing our current path to the root
sys.path.append(__file__.split("artiq")[0] + "artiq")

from repository.gui.components.ScientificSpin import ScientificSpin


class GUIClient:
    def __init__(self, server="137.222.69.28", port_control=3251, port_notify=3250):
        self.server = server
        self.port_control = port_control
        self.port_notify = port_notify

        self.rpc_clients: dict[AsyncioClient] = {}
        self.subscribers: dict[Subscriber] = {}
        self.booster = None

        self.booster_db = dict()
        self.schedule_db = dict()
        self.dataset_db = dict()
        self.dlcpro_db = dict()

        self.booster_callbacks = [[] for _ in range(8)]
        self.dataset_callbacks = {}
        self.schedule_callbacks = []
        self.dlcpro_callbacks = []

    async def connect(self):
        """Initialize connections."""
        # Connect RPC clients
        tasks = [
            self.connect_rpc("dataset_db"),
            self.connect_rpc("schedule"),
        ]

        # Connect subscribers
        def _dataset_create(data):
            logging.debug(f"New dataset:\n{data}")
            self.dataset_db = data
            return self.dataset_db

        def _dataset_update(mod):
            logging.debug(f"New dataset mod {mod}")
            for key in self.dataset_callbacks.keys():
                [cb() for cb in self.dataset_callbacks[key]]
            return

        tasks.append(
            self.connect_subscriber(
                "datasets",
                _dataset_create,
                _dataset_update,
            )
        )

        def _schedule_create(data):
            logging.debug(f"New schedule:\n{data}")
            self.schedule_db = data
            return self.schedule_db

        def _schedule_update(mod):
            logging.debug(f"New schedule mod {mod}")
            for cb in self.schedule_callbacks:
                cb()
            return

        tasks.append(
            self.connect_subscriber(
                "schedule",
                _schedule_create,
                _schedule_update,
            )
        )

        def _dlcpro_create(data):
            logging.debug(f"New DLCPro:\n{data}")
            self.dlcpro_db = data
            return self.dlcpro_db

        def _dlcpro_update(mod):
            logging.warning(f"New DLCPro mod {mod}")
            for cb in self.dlcpro_callbacks:
                cb()
            return

        tasks.append(
            self.connect_subscriber(
                "DLCProState",
                _dlcpro_create,
                _dlcpro_update,
                port=3275,
            )
        )

        # Connect booster via MQTT
        tasks.append(self.connect_booster())

        logging.info("Connecting to services...")
        await asyncio.gather(*tasks)

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

    async def connect_subscriber(
        self, target, target_builder, callback, disconnect=None, server=None, port=None
    ):
        server = self.server if server is None else server
        port = self.port_notify if port is None else port
        subscriber = Subscriber(target, target_builder, callback, disconnect)
        try:
            await asyncio.wait_for(
                subscriber.connect(
                    server,
                    port,
                ),
                5,
            )
        except asyncio.TimeoutError:
            logging.error(f"Failed to connect to Sub: {target} at {server}:{port}")
            return
        self.subscribers[target] = subscriber
        logging.info(f"Connected to Sub: {target} at {server}:{port}")

    async def connect_booster(self):
        """Initialize MQTT connection for booster telemetry."""

        # Define the callback for handling incoming MQTT messages
        def handle_booster_message(message):
            """Handle the incoming telemetry message."""
            logging.debug(f"New Booster message: {message.payload.decode()}")
            ch = int(message.topic.value[-1])
            data = message.payload.decode()
            self.booster_db[ch] = data

            # Call any registered callback for this channel
            for cb in self.booster_callbacks[ch]:
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
            logging.error(f"Failed to connect to Booster")
            return
        logging.info("Connected to Booster")

    def register_booster_callback(self, ch, cb):
        if ch == "*":
            [self.booster_callbacks[i].append(cb) for i in range(8)]
        elif ch in range(8):
            self.booster_callbacks[ch].append(cb)
        else:
            logging.error(f"Invalid booster channel {ch}")

    def register_dataset_callback(self, key, cb):
        if key not in self.dataset_callbacks:
            self.dataset_callbacks[key] = []
        self.dataset_callbacks[key].append(cb)
        cb()

    def register_schedule_callback(self, cb):
        self.schedule_callbacks.append(cb)
        cb()

    def register_dlcpro_callback(self, cb):
        self.dlcpro_callbacks.append(cb)
        cb()

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

        self.dlcpro_label = QLabel("DLCPro:")
        self.dlcpro_text = QTextEdit()
        self.dlcpro_text.setReadOnly(True)
        layout.addWidget(self.dlcpro_label)
        layout.addWidget(self.dlcpro_text)
        self.update_dlcpro()

        self.setLayout(layout)

    def update_dataset(self):
        self.dataset_text.setText(str(self.client.dataset_db))

    def update_schedule(self):
        self.schedule_text.setText(str(self.client.schedule_db))

    def update_booster(self):
        self.booster_text.setText(str(self.client.booster_db))

    def update_dlcpro(self):
        self.dlcpro_text.setText(str(self.client.dlcpro_db))

    def register_callbacks(self):
        self.client.register_dataset_callback("*", self.update_dataset)
        self.client.register_schedule_callback(self.update_schedule)
        self.client.register_booster_callback("*", self.update_booster)
        self.client.register_dlcpro_callback(self.update_dlcpro)


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
