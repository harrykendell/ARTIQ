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
    QSizePolicy,
)
from qasync import QEventLoop
from sipyco.sync_struct import Subscriber

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from toptica.lasersdk.utils.dlcpro import (
    extract_float_arrays,
    extract_lock_points,
    extract_lock_state,
)

sys.path.append(__file__.split("artiq")[0] + "artiq")
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

EMISSION_STYLES = {
    True: {  # Enabled
        "color": "green",
        "text": "ON",
        "background": "background-color: #e8ffe8;",
    },
    False: {  # Disabled
        "color": "red",
        "text": "OFF",
        "background_enabled": "background-color: #fff8e0;",
        "background_disabled": "background-color: #ffe8e8;",
    },
}

APP = None


class GUIClient:

    def __init__(self, server="137.222.69.28", port_control=3251, port_notify=3250):
        self.server = server
        self.port_control = port_control
        self.port_notify = port_notify
        self.subscribers = {}
        self.main_window = None
        self.tasks = []
        self.reconnect_tasks = {}  # Track reconnection tasks
        self.connection_status = {}  # Track connection status

        # Initialize data dictionaries
        self.datasets = dict()
        self.schedule = dict()
        self.dlcpro = dict()
        self.booster = dict()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.connect())
        logging.info("Successfully connected to all services")

    def set_main_window(self, window):
        """Set the main window for direct updates."""
        self.main_window = window

    async def connect(self):
        loop = asyncio.get_event_loop()

        # Initialize backoff tracking dictionary
        self.backoff_delays = {}
        self.max_backoff_delay = 60  # Maximum backoff in seconds
        self.initial_backoff_delay = 1  # Starting delay in seconds
        self.backoff_factor = 2.0  # Multiply by this each retry

        self.tasks.append(
            loop.create_task(
                self.connect_subscriber("datasets", self.datasets, self.port_notify)
            )
        )
        self.tasks.append(
            loop.create_task(
                self.connect_subscriber("schedule", self.schedule, self.port_notify)
            )
        )
        self.tasks.append(
            loop.create_task(self.connect_subscriber("DLCProState", self.dlcpro, 3271))
        )
        self.tasks.append(loop.create_task(self.connect_booster()))
        asyncio.gather(*self.tasks, return_exceptions=True)
        logging.debug("Connecting to services...")

    async def connect_subscriber(self, name, db: dict, port=None, server=None):
        port = self.port_notify if port is None else port
        server = self.server if server is None else server

        # Set initial connection status
        self.connection_status[name] = "connecting"
        if self.main_window:
            self.main_window.update_connection_status()

        def _create(data):
            db.update(data)
            # Reset backoff delay on successful connection
            self.backoff_delays[name] = self.initial_backoff_delay
            return db

        def _update(mod):
            if self.main_window:
                # Call the appropriate update method directly
                update_method = getattr(self.main_window, f"update_{name}")
                update_method(mod)
            return

        async def reconnect_subscriber():
            if getattr(APP, "shutdown", False):
                return
            # Get current backoff delay or initialize it
            current_delay = self.backoff_delays.get(name, self.initial_backoff_delay)

            # Log with current delay
            logging.info(f"Waiting {current_delay}s before reconnecting to {name}")
            self.connection_status[name] = f"reconnecting ({current_delay}s)"
            if self.main_window:
                self.main_window.update_connection_status()

            # Wait before attempting reconnection
            await asyncio.sleep(current_delay)

            # Calculate next backoff delay (with maximum limit)
            next_delay = min(
                current_delay * self.backoff_factor, self.max_backoff_delay
            )
            self.backoff_delays[name] = next_delay

            logging.info(f"Attempting to reconnect to {name} at {server}:{port}")
            self.connection_status[name] = "reconnecting"
            if self.main_window:
                self.main_window.update_connection_status()

            # Cancel any existing reconnection task
            if name in self.reconnect_tasks and not self.reconnect_tasks[name].done():
                self.reconnect_tasks[name].cancel()

            # Create new reconnection task
            self.reconnect_tasks[name] = asyncio.create_task(
                self.connect_subscriber(name, db, port, server)
            )

        def disconnect_cb(*args):
            logging.debug(f"Disconnected from {name} at {server}:{port}")
            self.connection_status[name] = "disconnected"
            if self.main_window:
                self.main_window.update_connection_status()

            # Schedule reconnection attempt
            asyncio.create_task(reconnect_subscriber())

        subscriber = Subscriber(name, _create, _update, disconnect_cb)
        try:
            await asyncio.wait_for(subscriber.connect(server, port), 5)
            self.subscribers[name] = subscriber
            self.connection_status[name] = "connected"
            if self.main_window:
                self.main_window.update_connection_status()
            logging.debug(f"Connected to {name} at {server}:{port}")
        except asyncio.TimeoutError:
            logging.error(f"Failed to connect to Sub: {name} at {server}:{port}")
            self.connection_status[name] = "failed"
            if self.main_window:
                self.main_window.update_connection_status()

            # Schedule reconnection attempt
            asyncio.create_task(reconnect_subscriber())

    async def connect_booster(self):
        self.connection_status["booster"] = "connecting"
        if self.main_window:
            self.main_window.update_connection_status()

        async def reconnect_booster():
            if getattr(APP, "shutdown", False):
                return
            # Get current backoff delay or initialize it
            current_delay = self.backoff_delays.get(
                "booster", self.initial_backoff_delay
            )

            # Log with current delay
            logging.info(f"Waiting {current_delay}s before reconnecting to Booster")
            self.connection_status["booster"] = f"reconnecting ({current_delay}s)"
            if self.main_window:
                self.main_window.update_connection_status()

            # Wait before attempting reconnection
            await asyncio.sleep(current_delay)

            # Calculate next backoff delay (with maximum limit)
            next_delay = min(
                current_delay * self.backoff_factor, self.max_backoff_delay
            )
            self.backoff_delays["booster"] = next_delay

            logging.debug("Attempting to reconnect to Booster")
            self.connection_status["booster"] = "reconnecting"
            if self.main_window:
                self.main_window.update_connection_status()

            # Cancel any existing reconnection task
            if (
                "booster" in self.reconnect_tasks
                and not self.reconnect_tasks["booster"].done()
            ):
                self.reconnect_tasks["booster"].cancel()

            # Create new reconnection task
            self.reconnect_tasks["booster"] = asyncio.create_task(
                self.connect_booster()
            )

        def disconnected_booster(*_):
            logging.info("Booster disconnected")
            self.connection_status["booster"] = "disconnected"
            if self.main_window:
                self.main_window.update_connection_status()

            # Schedule reconnection attempt
            asyncio.create_task(reconnect_booster())

        def handle_booster_message(message):
            logging.debug(f"New Booster message: {message.payload.decode()}")
            ch = int(message.topic.value[-1])
            data = message.payload.decode()
            self.booster[ch] = data

            # Reset backoff delay on successful message
            self.backoff_delays["booster"] = self.initial_backoff_delay

            if self.main_window:
                self.main_window.update_connection_status()
                self.main_window.update_booster(ch)

        try:
            async with aiomqtt.Client(self.server) as client:
                client._on_message = handle_booster_message
                client._on_disconnect = disconnected_booster
                await asyncio.wait_for(
                    client.subscribe("dt/sinara/booster/fc-0f-e7-23-77-30/telemetry/#"),
                    5,
                )
                self.connection_status["booster"] = "connected"
                # Reset backoff delay on successful connection
                self.backoff_delays["booster"] = self.initial_backoff_delay
                if self.main_window:
                    self.main_window.update_connection_status()
                logging.debug("Connected to Booster")

                async for message in client.messages:
                    handle_booster_message(message)

        except (aiomqtt.exceptions.MqttError, asyncio.TimeoutError):
            disconnected_booster()
        logging.debug("Connected to Booster")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.client = GUIClient()
        self.client.set_main_window(self)

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
            channel_layout.setContentsMargins(2, 2, 2, 2)

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
            laser_layout.setContentsMargins(2, 2, 2, 2)

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
            current_layout.setSpacing(0)
            dl_current_label = QLabel("Laser: --- mA")
            amp_current_label = QLabel("Amp: --- mA")

            current_layout.addWidget(dl_current_label)
            current_layout.addWidget(amp_current_label)

            current_widget = QWidget()
            current_widget.setLayout(current_layout)
            laser_layout.addWidget(current_widget)

            # Add spectrum plot for each laser
            spectrum_fig = Figure(figsize=(4, 2), dpi=100)
            spectrum_fig.patch.set_alpha(0)
            # Remove figure padding completely
            spectrum_fig.subplots_adjust(
                left=0, right=1, top=1, bottom=0, wspace=0, hspace=0
            )

            spectrum_canvas = FigureCanvas(spectrum_fig)
            spectrum_axes = spectrum_fig.add_subplot(111)
            spectrum_axes.patch.set_alpha(0)

            # Fill the entire axes area
            spectrum_axes.set_position([0, 0, 1, 1])

            # Allow expansion in both directions
            spectrum_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            # Set a minimum height, but allow expansion
            spectrum_canvas.setMinimumHeight(80)

            # Add to layout with stretch factor
            laser_layout.addWidget(spectrum_canvas, 1)

            frame.setLayout(laser_layout)
            self.dlc_frames.append(
                {
                    "frame": frame,
                    "name": name_label,
                    "state": state_label,
                    "dl_current": dl_current_label,
                    "amp_current": amp_current_label,
                    "lock": lock_label,
                    "spectrum_canvas": spectrum_canvas,
                    "spectrum_axes": spectrum_axes,
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
        fig = Figure(figsize=(7, 8))
        self.canvas = FigureCanvas(fig)

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
        self.elapsed_time_label = QLabel(
            "<span style='font-size: 200%;'>📷</span> ... ago"
        )
        self.elapsed_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_controls.addWidget(self.elapsed_time_label)

        # Add right controls to main layout
        bottom_bar_layout.addLayout(right_controls)

        layout.addLayout(bottom_bar_layout)

        self.setLayout(layout)

    def update_elapsed_time(self):
        """Update the elapsed time display"""
        now = time.time()

        image_time = self.client.datasets.get("Images.absorption.timestamp")

        if not image_time:
            self.elapsed_time_label.setText("..m ..s ago")
            return

        elapsed = int(now - image_time[1])
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)

        self.elapsed_time_label.setText(
            f"{hours}h" * (hours > 0)
            + f" {minutes}m" * (minutes > 0)
            + f" {seconds}s" * (hours == 0)
            + " ago"
        )

    def update_datasets(self, mod):
        if "Images.absorption" not in str(mod):
            return
        self.update_elapsed_time()

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

        self.canvas.figure.clear()
        _, axes = self.absimg.plot(fig=self.canvas.figure)
        self.canvas.axes = axes
        self.canvas.draw()

        # Update status - atom number, r-squared, sigma_x, sigma_y,
        # expansion time
        atom_number = self.absimg.atom_number
        r_squared = self.absimg.fit.summary()["rsquared"]
        sigmax = self.absimg.fit.best_values["sx"] * self.absimg.physical_scale * 1e3
        sigmay = self.absimg.fit.best_values["sy"] * self.absimg.physical_scale * 1e3
        expansion_time = self.client.datasets.get("Images.absorption.expansion_time")[1]

        if not self.save_button.isEnabled():
            self.save_button.setEnabled(True)
            self.layout().addWidget(self.canvas)
            self.toolbar = NavigationToolbar(self.canvas, self)
            self.layout().addWidget(self.toolbar)
            # Add status label at the bottom
            self.status_label = QLabel("Waiting for data...")
            self.status_label.setAlignment(Qt.AlignCenter)
            self.status_label.setStyleSheet("font-size: 10pt;")
            self.status_label.setWordWrap(True)
            self.layout().addWidget(self.status_label)
            self.resize(self.width(), self.height() + 500)

        self.status_label.setText(
            f"""<div style="text-align:center; margin:0; padding:0">
                <span style="font-weight:bold">Atoms:</span>\
                {atom_number:.2e} &nbsp;
                <span style="font-weight:bold">Expansion:</span>\
                {expansion_time*1e3:.2f} ms &nbsp;
                <span style="font-weight:bold">Sigma:</span>\
                ({sigmax:.2f}, {sigmay:.2f}) mm<br>
                <span style="color:#CCC"><b>R-squared:</b>\
                {r_squared:.2f}</span>
            </div>"""
        )

    def update_schedule(self, mod):
        self.update_elapsed_time()

        text = "<b>Running:</b>\t---"
        for _key, value in self.client.schedule.items():
            if value["status"] == "running":
                text = f"<b>Running:</b>\t{value['expid']['class_name']}"
        self.schedule_text.setText(text)

    def update_DLCProState(self, mod):
        """Update the DLCPro state display."""
        if not self.client.dlcpro:
            return

        # Get emission and connection states
        emission_enabled = self.client.dlcpro.get("emission", False)
        emission_button_enabled = self.client.dlcpro.get(
            "emission-button-enabled", False
        )

        # Update connection and emission status
        self._update_dlc_connection_status(emission_enabled)

        # Update frame styling based on emission state
        self._update_dlc_frame_style(emission_enabled, emission_button_enabled)

        # Update laser displays
        self._update_laser_displays()

    def _update_dlc_connection_status(self, emission_enabled):
        """Update the DLCPro connection status display."""
        CONNECTION_COLORS = {
            "connected": "black",
            "connecting": "orange",
            "reconnecting": "orange",
            "disconnected": "red",
            "failed": "red",
        }

        connection_status = self.client.connection_status.get(
            "DLCProState", "disconnected"
        )
        conn_color = CONNECTION_COLORS.get(connection_status, "red")

        # Set emission state color and text
        on_off_color = "green" if emission_enabled else "red"
        on_off_text = "ON" if emission_enabled else "OFF"

        # Update label
        self.dlc_status_label.setText(
            f"<span style='color:{conn_color};'>DLCPro:</span> <span style='color:{on_off_color};'>{on_off_text}</span>"
        )
        self.dlc_status_label.setStyleSheet("font-weight: bold;")

    def _update_dlc_frame_style(self, emission_enabled, emission_button_enabled):
        """Update the DLCPro frame styling based on emission state."""
        if emission_enabled:
            self.dlc_outer_frame.setStyleSheet("background-color: #e8ffe8;")
        else:
            self.dlc_outer_frame.setStyleSheet(
                "background-color: #fff8e0;"
                if emission_button_enabled
                else "background-color: #ffe8e8;"
            )

    def _update_laser_displays(self):
        """Update the individual laser displays."""
        # Define number of lasers as a constant
        NUM_LASERS = 2

        for i in range(1, NUM_LASERS + 1):
            self._update_laser_display(i)
            self._update_laser_plot(i)

    def _update_laser_display(self, laser_num):
        """Update a single laser's display elements."""
        laser_prefix = f"laser{laser_num}"

        # Get laser data
        laser_enabled = self.client.dlcpro.get(f"{laser_prefix}:enabled", False)
        emission_enabled = self.client.dlcpro.get("emission", False)
        dl_current = self.client.dlcpro.get(f"{laser_prefix}:dl:cc:current_set", 0.0)
        amp_current = self.client.dlcpro.get(f"{laser_prefix}:amp:cc:current_set", 0.0)
        lock_enabled = self.client.dlcpro.get(
            f"{laser_prefix}:dl:lock:lock_enabled", False
        )
        label = self.client.dlcpro.get(f"{laser_prefix}:label", f"Laser {laser_num}")

        # Update display
        self.dlc_frames[laser_num - 1]["name"].setText(f"<b>{label}</b>")

        self._update_device_display(
            "dlc",
            laser_num - 1,
            (
                DeviceState.ENABLED
                if emission_enabled and laser_enabled
                else DeviceState.DISABLED
            ),
            f"Laser: {dl_current:.1f} mA",
            amp_current_text=f"Amp: {amp_current:.1f} mA",
            lock_state=DeviceState.LOCKED if lock_enabled else DeviceState.UNLOCKED,
        )

    def _update_laser_plot(self, laser_num):
        """Update the laser spectrum plot."""
        laser_prefix = f"laser{laser_num}"
        idx = laser_num - 1

        # Get canvas and axes
        canvas = self.dlc_frames[idx]["spectrum_canvas"]
        fig = canvas.figure
        axes = self.dlc_frames[idx]["spectrum_axes"]
        axes.clear()

        # Only update if signal is available
        if not self.client.dlcpro.get(f"{laser_prefix}:scope:channel1:signal"):
            return

        # Get the spectrum data
        scope_data = extract_float_arrays(
            "xyY", self.client.dlcpro.get(f"{laser_prefix}:scope:data")
        )
        raw_lock_candidates = self.client.dlcpro.get(
            f"{laser_prefix}:dl:lock:candidates"
        )
        lock_candidates = extract_lock_points("clt", raw_lock_candidates)
        lock_state = extract_lock_state(raw_lock_candidates)

        # Plot main spectrum data
        self._plot_spectrum_data(axes, scope_data, lock_candidates, lock_state)

        # Plot background
        background_data = extract_float_arrays(
            "xy",
            self.client.dlcpro.get(f"{laser_prefix}:dl:lock:background_trace"),
        )
        axes.plot(
            background_data["x"],
            background_data["y"],
            linestyle="solid",
            color="k",
            zorder=0,
            linewidth=1.0,
        )

        # Style the plot
        self._style_spectrum_plot(axes, fig)

        # Update the canvas
        canvas.draw_idle()

    def _plot_spectrum_data(self, axes, scope_data, lock_candidates, lock_state):
        """Plot the spectrum data and lock points."""
        # Define constants
        LOCK_STATE_SELECTED = 3  # 'Selected' state

        # Plot first channel (red)
        axes.plot(
            scope_data["x"],
            scope_data["y"],
            linestyle="solid",
            color="red",
            zorder=1,
            linewidth=1.0,
        )

        # Plot lock candidates if available
        if "c" in lock_candidates:
            axes.plot(
                lock_candidates["c"]["x"],
                lock_candidates["c"]["y"],
                linestyle="None",
                marker="o",
                markersize=4.0,
                color="grey",
                zorder=2,
            )

        # Plot selected lock point if available
        if "l" in lock_candidates and lock_state == LOCK_STATE_SELECTED:
            axes.plot(
                lock_candidates["l"]["x"],
                lock_candidates["l"]["y"],
                linestyle="None",
                marker="o",
                markersize=6.0,
                color="red",
                markerfacecolor="none",
                zorder=3,
            )

        # Plot lock tracking position if available
        if "t" in lock_candidates:
            axes.plot(
                lock_candidates["t"]["x"],
                lock_candidates["t"]["y"],
                linestyle="None",
                marker="o",
                markersize=8.0,
                color="red",
                markerfacecolor="none",
                zorder=3,
            )

    def _style_spectrum_plot(self, axes, fig):
        """Apply styling to the spectrum plot."""
        # Make background transparent
        axes.patch.set_alpha(0)

        # Remove margins and padding
        axes.margins(0, 0)

        # Style spines
        for spine in axes.spines.values():
            spine.set_color("#aaaaaa")
            spine.set_linewidth(1.0)

        # Remove ticks
        axes.set_xticks([])
        axes.set_yticks([])

        # Ensure plot fills the figure
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    def update_booster(self, channel: int) -> None:
        """
        Update the booster channel display.

        Args:
            channel: The booster channel number (0-7)
        """
        # Define constants
        LOW_POWER_THRESHOLD = 5.0  # dBm

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

                # Map state strings to DeviceState enum using dictionary
                STATE_MAPPING = {
                    DeviceState.ENABLED.value: (
                        DeviceState.LOW_POWER
                        if output_power < LOW_POWER_THRESHOLD
                        else DeviceState.ENABLED
                    ),
                    DeviceState.DISABLED.value: DeviceState.DISABLED,
                }

                # Default to UNKNOWN if not in mapping
                if "Tripped" in state_str:
                    state = DeviceState.TRIPPED
                else:
                    state = STATE_MAPPING.get(state_str, DeviceState.UNKNOWN)

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

    def update_connection_status(self):
        # Update UI elements for each service
        for name, status in self.client.connection_status.items():
            if status == "connected":
                color = "black"
            elif status in ["connecting", "reconnecting"]:
                color = "orange"
            else:  # disconnected or failed
                color = "red"

            # Update corresponding UI elements based on the service
            if name == "booster":
                self.booster_label.setStyleSheet(f"font-weight: bold; color: {color};")

            elif name == "datasets":
                self.elapsed_time_label.setStyleSheet(f"color: {color};")

            elif name == "schedule":
                self.schedule_text.setStyleSheet(f"color: {color};")

            elif name == "DLCProState":
                # Update only connection status part of DLCPro label
                # ON/OFF status is handled by update_DLCProState
                emission_enabled = (
                    self.client.dlcpro.get("emission", False)
                    if self.client.dlcpro
                    else False
                )
                on_off_text = "ON" if emission_enabled else "OFF"
                on_off_color = "green" if emission_enabled else "red"

                self.dlc_status_label.setText(
                    f"<span style='color:{color};'>DLCPro:</span>"
                    f" <span style='color:{on_off_color};'>{on_off_text}</span>"
                )
                self.dlc_status_label.setStyleSheet("font-weight: bold;")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    APP = QApplication(sys.argv)
    APP.setStyle("Fusion")

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
    APP.setPalette(light_palette)

    loop = QEventLoop(APP)
    asyncio.set_event_loop(loop)

    main_window = MainWindow()

    main_window.show()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Shutting down...")
    finally:
        APP.shutdown = True
        print("Shutting down ARTIQ GUI...")
        # Ensure clean shutdown
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
