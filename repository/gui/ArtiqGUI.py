import asyncio
import json
import logging
import sys
import time
from enum import Enum

import aiomqtt
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qasync import QEventLoop
from sipyco.sync_struct import Subscriber

sys.path.append(__file__.split("artiq")[0] + "artiq")
from repository.imaging.applet import MatplotlibCanvas  # noqa: E402
from repository.imaging.processor import AbsImage  # noqa: E402


class DeviceState(Enum):
    ENABLED = "Enabled"
    DISABLED = "Disabled"
    ERROR = "Error"
    UNKNOWN = "Unknown"
    LOW_POWER = "Low"
    LOCKED = "Locked"
    UNLOCKED = "Unlocked"
    TRIPPED = "Tripped"


ERROR = {
    "state": "color: red; font-weight: bold;",
    "frame": "background-color: #ffe8e8;",
    "value": "",
}
WORKING = {
    "state": "color: green; font-weight: bold;",
    "frame": "background-color: #e8ffe8;",
    "value": "",
}
DUBIOUS = {
    "state": "color: #aa6600; font-weight: bold;",
    "frame": "background-color: #fff8e0;",
    "value": "font-weight: bold;",
}
UNKOWN = {
    "state": "",
    "frame": "background-color: #f0f0f0;",
    "value": "",
}
DEVICE_STYLES = {
    DeviceState.ENABLED: WORKING,
    DeviceState.LOW_POWER: DUBIOUS,
    DeviceState.UNLOCKED: DUBIOUS,
    DeviceState.ERROR: ERROR,
    DeviceState.DISABLED: ERROR,
    DeviceState.TRIPPED: ERROR,
    DeviceState.UNKNOWN: UNKOWN,
    DeviceState.LOCKED: {
        "state": "color: blue; font-weight: bold;",
        "frame": "background-color: #e8e8ff;",
        "value": "font-weight: bold;",
    },
}


class GUIClient:
    def __init__(self, server="137.222.69.28", port_control=3251, port_notify=3250):
        self.server = server
        self.port_control = port_control
        self.port_notify = port_notify
        self.subscribers = {}
        self.main_window = None

        # Initialize data dictionaries
        self.datasets = dict()
        self.schedule = dict()
        self.dlcpro = dict()
        self.booster = dict()

    def set_main_window(self, window):
        """Set the main window for direct updates."""
        self.main_window = window

    async def connect(self):
        loop = asyncio.get_event_loop()

        loop.create_task(
            self.connect_subscriber("datasets", self.datasets, self.port_notify)
        )
        loop.create_task(
            self.connect_subscriber("schedule", self.schedule, self.port_notify)
        )
        loop.create_task(self.connect_subscriber("DLCProState", self.dlcpro, 3271))

        loop.create_task(self.connect_booster())
        logging.info("Connecting to services...")

    async def connect_subscriber(self, name, db: dict, port=None, server=None):
        port = self.port_notify if port is None else port
        server = self.server if server is None else server

        def _create(data):
            db.update(data)
            return db

        def _update(mod):
            if self.main_window:
                # Call the appropriate update method directly
                update_method = getattr(self.main_window, f"update_{name}")
                update_method(mod)
            return

        subscriber = Subscriber(name, _create, _update, None)
        try:
            await asyncio.wait_for(subscriber.connect(server, port), 5)
        except asyncio.TimeoutError:
            logging.error(f"Failed to connect to Sub: {name} at {server}:{port}")
            return
        self.subscribers[name] = subscriber
        logging.info(f"Connected to Sub: {name} at {server}:{port}")

    async def connect_booster(self):
        def handle_booster_message(message):
            logging.debug(f"New Booster message: {message.payload.decode()}")
            ch = int(message.topic.value[-1])
            data = message.payload.decode()
            self.booster[ch] = data

            if self.main_window:
                self.main_window.update_booster(ch)

        try:
            async with aiomqtt.Client(self.server) as client:
                await asyncio.wait_for(
                    client.subscribe("dt/sinara/booster/fc-0f-e7-23-77-30/telemetry/#"),
                    5,
                )
                client._on_message = handle_booster_message
                async for message in client.messages:
                    handle_booster_message(message)
        except (aiomqtt.exceptions.MqttError, asyncio.TimeoutError) as e:
            logging.error(f"Failed to connect to Booster:\n{e}")
            return
        logging.info("Connected to Booster")

    async def disconnect(self):
        for subscriber in self.subscribers.values():
            await subscriber.close()
        logging.info("Disconnected from all connections.")


class MainWindow(QWidget):
    def __init__(self, client: GUIClient):
        super().__init__()
        self.client = client
        self.client.set_main_window(self)  # Set this window for direct updates

        # Add Active tracking
        self.last_update_time = None

        self.setWindowTitle("ARTIQ GUI")
        self.setGeometry(100, 100, 550, 400)
        self.initUI()

        # Create a timer that updates every second
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_elapsed_time)
        self.update_timer.start(1000)  # Update every second

    def initUI(self):
        layout = QVBoxLayout()

        booster_layout = QGridLayout()
        booster_layout.setSpacing(8)
        self.booster_frames = []

        for i in range(8):
            frame = QFrame()
            frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
            frame.setLineWidth(2)

            channel_layout = QVBoxLayout()
            channel_layout.setSpacing(0)
            channel_layout.setContentsMargins(2, 2, 2, 10)

            header_layout = QGridLayout()
            header_layout.setSpacing(0)
            ch_label = QLabel(f"<b>Ch {i}</b>")
            state_label = QLabel(DeviceState.UNKNOWN.value)
            header_layout.addWidget(ch_label, 0, 0)
            header_layout.addWidget(state_label, 0, 1, Qt.AlignRight)

            header_widget = QWidget()
            header_widget.setLayout(header_layout)
            channel_layout.addWidget(header_widget)

            power_label = QLabel("--.- → --.- dBm")
            power_label.setAlignment(Qt.AlignCenter)
            channel_layout.addWidget(power_label)

            reflected_label = QLabel("↻ --.- dBm")
            reflected_label.setAlignment(Qt.AlignCenter)
            channel_layout.addWidget(reflected_label)

            frame.setLayout(channel_layout)
            self.booster_frames.append(
                {
                    "frame": frame,
                    "ch_label": ch_label,
                    "state": state_label,
                    "power": power_label,
                    "reflected": reflected_label,
                }
            )

            row = i // 4
            col = i % 4
            booster_layout.addWidget(frame, row, col)

        booster_outer_frame = QFrame()
        booster_outer_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        booster_outer_frame.setLineWidth(2)
        self.booster_outer_frame = booster_outer_frame

        booster_label = QLabel("Booster")
        booster_label.setAlignment(Qt.AlignCenter)
        booster_label.setStyleSheet("font-weight: bold;")
        self.booster_label = booster_label

        booster_outer_layout = QVBoxLayout()
        booster_outer_layout.addWidget(booster_label)
        booster_outer_layout.addLayout(booster_layout)
        booster_outer_frame.setLayout(booster_outer_layout)
        layout.addWidget(booster_outer_frame)

        dlc_outer_frame = QFrame()
        dlc_outer_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        dlc_outer_frame.setLineWidth(2)
        self.dlc_outer_frame = dlc_outer_frame

        dlc_layout = QGridLayout()
        dlc_layout.setSpacing(8)
        self.dlc_frames = []

        for i in range(2):
            frame = QFrame()
            frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
            frame.setLineWidth(2)

            laser_layout = QVBoxLayout()
            laser_layout.setSpacing(0)
            laser_layout.setContentsMargins(2, 2, 2, 10)

            header_layout = QGridLayout()
            header_layout.setSpacing(0)
            name_label = QLabel(f"<b>Laser {i+1}</b>")
            state_label = QLabel(DeviceState.UNKNOWN.value)
            lock_label = QLabel(DeviceState.UNLOCKED.value)

            header_layout.addWidget(name_label, 0, 0)
            header_layout.addWidget(state_label, 0, 1, Qt.AlignRight)
            header_layout.addWidget(lock_label, 0, 2, Qt.AlignRight)

            header_widget = QWidget()
            header_widget.setLayout(header_layout)
            laser_layout.addWidget(header_widget)

            current_layout = QHBoxLayout()
            current_layout.setSpacing(5)
            dl_current_label = QLabel("Laser: --- mA")
            amp_current_label = QLabel("Amp: --- mA")

            current_layout.addWidget(dl_current_label)
            current_layout.addWidget(amp_current_label)

            current_widget = QWidget()
            current_widget.setLayout(current_layout)
            laser_layout.addWidget(current_widget)

            frame.setLayout(laser_layout)
            self.dlc_frames.append(
                {
                    "frame": frame,
                    "name": name_label,
                    "state": state_label,
                    "dl_current": dl_current_label,
                    "amp_current": amp_current_label,
                    "lock": lock_label,
                }
            )

            dlc_layout.addWidget(frame, 0, i)

        dlc_status_label = QLabel("DLCPro")
        dlc_status_label.setAlignment(Qt.AlignCenter)
        dlc_status_label.setStyleSheet("font-weight: bold;")
        self.dlc_status_label = dlc_status_label

        outer_layout = QVBoxLayout()
        outer_layout.addWidget(dlc_status_label)
        outer_layout.addLayout(dlc_layout)
        dlc_outer_frame.setLayout(outer_layout)
        layout.addWidget(dlc_outer_frame)

        # Create the matplotlib canvas
        self.canvas = MatplotlibCanvas(self, width=8, height=8)

        # Create a single bottom bar layout
        bottom_bar_layout = QHBoxLayout()

        # Experiment status (left side)
        self.schedule_text = QLabel("<b>Running:</b>\t---")
        self.schedule_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        bottom_bar_layout.addWidget(self.schedule_text, 1)  # Takes stretch priority 1

        # Add spacer to push everything else to the right
        bottom_bar_layout.addStretch(1)

        # Right-aligned controls in their own layout
        right_controls = QHBoxLayout()
        right_controls.setSpacing(10)  # Space between button and timer

        # Save button
        save_button = QPushButton("Save Datasets")
        save_button.clicked.connect(self.saveDatasets)
        save_button.setEnabled(False)
        self.save_button = save_button
        right_controls.addWidget(save_button)

        # Elapsed time
        self.elapsed_time_label = QLabel("↻ ... ago")
        self.elapsed_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_controls.addWidget(self.elapsed_time_label)

        # Add right controls to main layout
        bottom_bar_layout.addLayout(right_controls)

        layout.addLayout(bottom_bar_layout)

        self.setLayout(layout)

    def update_elapsed_time(self, reset=False):
        """Update the elapsed time display"""
        if reset:
            self.last_update_time = time.time()
        if self.last_update_time is None:
            self.elapsed_time_label.setText("↻ ... ago")
            return

        elapsed = int(time.time() - self.last_update_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            time_str = f"{hours}h {minutes}m ago"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s ago"
        else:
            time_str = f"{seconds}s ago"

        self.elapsed_time_label.setText(f"↻ {time_str}")

    def update_datasets(self, mod):
        if mod["action"] != "delitem":
            self.update_elapsed_time(True)
        if (
            mod["action"] != "init"
            and "Images.absorption" not in f"{mod['path']}.{mod['key']}"
        ):
            return

        # if absorption images changed then redo AbsImage
        tof = self.client.datasets.get("Images.absorption.TOF")
        ref = self.client.datasets.get("Images.absorption.REF")
        bg = self.client.datasets.get("Images.absorption.BG")
        if tof is None or ref is None or bg is None:
            return

        self.absimg = AbsImage(
            data=tof[1],
            ref=ref[1],
            bg=bg[1],
            magnification=0.5,  # Set default magnification
        )

        self.canvas.fig.clear()
        _, axes = self.absimg.plot(fig=self.canvas.fig)
        self.canvas.axes = axes
        self.canvas.draw()

        if not self.save_button.isEnabled():
            self.save_button.setEnabled(True)
            self.layout().addWidget(self.canvas)
            self.resize(self.width(), self.height() + 500)

    def update_schedule(self, mod):
        self.update_elapsed_time(True)

        text = "<b>Running:</b>\t---"
        for key, value in self.client.schedule.items():
            if value["status"] == "running":
                text = f"<b>Running:</b>\t{value['expid']['class_name']}"
        self.schedule_text.setText(text)

    def update_DLCProState(self, mod):
        if not self.client.dlcpro:
            return

        emission_enabled = self.client.dlcpro.get("emission", False)
        emission_button_enabled = self.client.dlcpro.get(
            "emission-button-enabled", False
        )

        if emission_enabled:
            self.dlc_status_label.setText("DLCPro: ON")
            self.dlc_status_label.setStyleSheet("font-weight: bold; color: green;")
            self.dlc_outer_frame.setStyleSheet("background-color: #e8ffe8;")
        else:
            self.dlc_status_label.setText("DLCPro: OFF")
            self.dlc_status_label.setStyleSheet("font-weight: bold; color: red;")
            self.dlc_outer_frame.setStyleSheet(
                "background-color: #fff8e0;"
                if emission_button_enabled
                else "background-color: #ffe8e8;"
            )

        for i in range(1, 3):
            laser_prefix = f"laser{i}:"
            laser_enabled = self.client.dlcpro.get(f"{laser_prefix}enabled", False)
            dl_current = self.client.dlcpro.get(f"{laser_prefix}dl:cc:current-set", 0.0)
            amp_current = self.client.dlcpro.get(
                f"{laser_prefix}amp:cc:current-set", 0.0
            )
            lock_enabled = self.client.dlcpro.get(
                f"{laser_prefix}dl:lock:lock-enabled", False
            )
            label = self.client.dlcpro.get(f"{laser_prefix}label", f"Laser {i}")
            self.dlc_frames[i - 1]["name"].setText(f"<b>{label}</b>")

            self._update_device_display(
                "dlc",
                i - 1,
                (
                    DeviceState.ENABLED
                    if emission_enabled and laser_enabled
                    else DeviceState.DISABLED
                ),
                f"Laser: {dl_current:.1f} mA",
                amp_current_text=f"Amp: {amp_current:.1f} mA",
                lock_state=DeviceState.LOCKED if lock_enabled else DeviceState.UNLOCKED,
            )

    def update_booster(self, channel):
        LOW_POWER_THRESHOLD = 5.0

        state = DeviceState.UNKNOWN
        power_text = "--.- → --.- dBm"
        reflected_text = "↻ --.- dBm"

        if channel in self.client.booster:
            try:
                data = json.loads(self.client.booster[channel])
                state_str = data.get("state", DeviceState.UNKNOWN.value)
                input_power = data.get("input_power", 0.0)
                output_power = data.get("output_power", 0.0)
                reflected_power = data.get("reflected_power", 0.0)

                power_text = f"{input_power:.1f} → {output_power:.1f} dBm"
                reflected_text = f"↻ {reflected_power:.1f} dBm"

                if state_str == DeviceState.ENABLED.value:
                    state = (
                        DeviceState.LOW_POWER
                        if output_power < LOW_POWER_THRESHOLD
                        else DeviceState.ENABLED
                    )
                elif state_str == DeviceState.DISABLED.value:
                    state = DeviceState.DISABLED
                elif "Tripped" in state_str:
                    state = DeviceState.TRIPPED
                else:
                    state = DeviceState.UNKNOWN

            except (json.JSONDecodeError, KeyError):
                state = DeviceState.ERROR

        self._update_device_display(
            "booster", channel, state, power_text, reflected_text=reflected_text
        )

    def _update_device_display(
        self,
        device_type,
        idx,
        state,
        value_text,
        reflected_text=None,
        amp_current_text=None,
        lock_state=None,
    ):
        if device_type == "booster":
            frame = self.booster_frames[idx]
            frame["state"].setText(state.value)
            frame["power"].setText(value_text)
            if reflected_text:
                frame["reflected"].setText(reflected_text)

            styles = DEVICE_STYLES[state]
            frame["state"].setStyleSheet(styles["state"])
            frame["power"].setStyleSheet(styles["value"])
            frame["frame"].setStyleSheet(styles["frame"])

        elif device_type == "dlc":
            frame = self.dlc_frames[idx]
            frame["state"].setText(state.value)
            frame["dl_current"].setText(value_text)
            if amp_current_text:
                frame["amp_current"].setText(amp_current_text)
            if lock_state:
                frame["lock"].setText(lock_state.value)

            styles = DEVICE_STYLES[state]
            frame["state"].setStyleSheet(styles["state"])
            frame["frame"].setStyleSheet(styles["frame"])

            if lock_state:
                lock_styles = DEVICE_STYLES[lock_state]
                frame["lock"].setStyleSheet(lock_styles["state"])

    def saveDatasets(self):
        data = {key: val[1] for key, val in self.client.datasets.items()}
        print("Saving datasets, type: ", type(data))
        np.save("datasets.npy", data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    light_palette = QPalette()
    light_palette.setColor(QPalette.Window, QColor(240, 240, 240))
    light_palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.Base, QColor(255, 255, 255))
    light_palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
    light_palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    light_palette.setColor(QPalette.ToolTipText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.Text, QColor(0, 0, 0))
    light_palette.setColor(QPalette.Button, QColor(240, 240, 240))
    light_palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
    light_palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    light_palette.setColor(QPalette.Link, QColor(0, 0, 255))
    light_palette.setColor(QPalette.Highlight, QColor(76, 163, 224))
    light_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(light_palette)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    server = "137.222.69.28"

    client = GUIClient(server)
    main_window = MainWindow(client)

    loop.create_task(client.connect())
    app.aboutToQuit.connect(lambda: loop.create_task(client.disconnect()))

    main_window.show()
    loop.run_forever()
