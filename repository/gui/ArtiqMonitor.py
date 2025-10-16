import asyncio
import logging
import sys
import json
from enum import Enum
import time


import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
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

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from toptica.lasersdk.utils.dlcpro import (
    extract_float_arrays,
    extract_lock_points,
    extract_lock_state,
)


sys.path.append(__file__.split("artiq")[0] + "artiq")
from repository.gui.monitor_client import MonitorClient  # noqa: E402
from repository.imaging.processor import AbsImage  # noqa: E402
from repository.imaging.absorption_image import MAGNIFICATION  # noqa: E402


class DeviceState(Enum):
    ENABLED = "Enabled"
    POWERED = "Powered"
    DISABLED = "Disabled"
    OFF = "Off"
    ERROR = "Error"
    UNKNOWN = "Unknown"
    LOW_POWER = "Low"
    LOCKED = "Locked"
    UNLOCKED = "Unlocked"
    TRIPPED = "Tripped"


ERROR: dict[str, str] = {
    "state": "color: red; font-weight: bold;",
    "frame": "background-color: #ffe8e8;",
    "value": "",
}
WORKING: dict[str, str] = {
    "state": "color: green; font-weight: bold;",
    "frame": "background-color: #e8ffe8;",
    "value": "",
}
DUBIOUS: dict[str, str] = {
    "state": "color: #aa6600; font-weight: bold;",
    "frame": "background-color: #fff8e0;",
    "value": "font-weight: bold;",
}
UNKOWN: dict[str, str] = {
    "state": "",
    "frame": "background-color: #f0f0f0;",
    "value": "",
}
DEVICE_STYLES: dict[DeviceState, dict[str, str]] = {
    DeviceState.ENABLED: WORKING,
    DeviceState.LOW_POWER: DUBIOUS,
    DeviceState.POWERED: DUBIOUS,
    DeviceState.UNLOCKED: DUBIOUS,
    DeviceState.ERROR: ERROR,
    DeviceState.OFF: ERROR,
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


class MainWindow(QWidget):
    def __init__(self, app) -> None:
        super().__init__()
        self.client = MonitorClient(app=app)
        self.client.set_main_window(self)

        # Register for service state change notifications
        for _, service in self.client.services.items():
            service.state_change_callback = (
                lambda name, old, new: self.handle_service_state_change(name, old, new)
            )

        self.setWindowTitle("ARTIQ Monitor")
        self.setGeometry(100, 100, 550, 400)
        self.initUI()

        # Create a timer that updates every second
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start(250)  # Update every second

    def initUI(self) -> None:
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
            name_label = QLabel(f"<b>Laser {i + 1}</b>")
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

            # Allow expansion in both directions
            spectrum_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            # Set a minimum height, but allow expansion
            spectrum_canvas.setMinimumHeight(80)

            spectrum_axes.patch.set_alpha(0)

            # Remove margins and padding
            spectrum_axes.margins(0, 0)

            # Style spines
            for spine in spectrum_axes.spines.values():
                spine.set_color("#aaaaaa")
                spine.set_linewidth(1.0)

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
                    "x_lim": [np.inf, -np.inf],
                    "y_lim": [np.inf, -np.inf],
                }
            )

            dlc_layout.addWidget(frame, 0, i)

        dlc_status_label = QLabel("DLCPro")
        dlc_status_label.setAlignment(Qt.AlignCenter)
        dlc_status_label.setStyleSheet("font-weight: bold;")
        self.dlc_status_label = dlc_status_label

        # Create a horizontal layout for the DLC header
        dlc_header_layout = QHBoxLayout()
        dlc_header_layout.addWidget(dlc_status_label, 1)  # Give label more stretch

        outer_layout = QVBoxLayout()
        outer_layout.addLayout(
            dlc_header_layout
        )  # Add header layout instead of just label
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
        self.update()

    def update(self) -> None:
        """Update the elapsed time display and connection status"""
        now = time.time()

        # Only try to get data if the datasets service is connected
        datasets_service = self.client.services.get("datasets")
        if datasets_service and datasets_service.state.name == "CONNECTED":
            image_time = self.client.datasets.get("Images.absorption.timestamp")
        else:
            image_time = None

        if not image_time:
            self.elapsed_time_label.setText("..m ..s ago")
        else:
            elapsed = int(now - image_time[1])
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)

            self.elapsed_time_label.setText(
                f"{hours}h" * (hours > 0)
                + f" {minutes}m" * (minutes > 0)
                + f" {seconds}s" * (hours == 0)
                + " ago"
            )

        # Only try DLCPro update if service is connected
        dlcpro_service = self.client.services.get("dlcpro")
        if dlcpro_service and dlcpro_service.state.name == "CONNECTED":
            try:
                self.update_DLCProState()
            except Exception as e:
                logging.error(f"Failed to update DLCPro state: {e}")
                # Don't set client.dlcpro to None as the service handles reconnection

    # Always update connection status to show current state
    def update_connection_status(self) -> None:
        """Update the connection status display for all services."""
        # Create a mapping from service states to display colors
        state_colors = {"CONNECTED": "green", "CONNECTING": "orange", "BACKOFF": "red"}

        # Update UI elements for each service
        for name, service in self.client.services.items():
            # Get current state and convert to string
            current_state = service.state.name
            # Get appropriate color based on state
            color = state_colors.get(current_state, "red")

            # Update corresponding UI elements based on the service
            if name == "booster":
                self.booster_label.setStyleSheet(f"font-weight: bold; color: {color};")

            elif name == "datasets":
                self.elapsed_time_label.setStyleSheet(f"color: {color};")

            elif name == "schedule":
                self.schedule_text.setStyleSheet(f"color: {color};")

            elif name == "dlcpro":
                # Handle DLCPro specially to preserve ON/OFF status
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

    def update_datasets(self, mod) -> None:
        if "Images.absorption" not in str(mod):
            return
        self.update()

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
            magnification=MAGNIFICATION,  # Set default magnification
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
        centroid_y = self.absimg.centroid[0]
        centroid_x = self.absimg.centroid[1]
        PSD = self.absimg.phase_space_density[2]
        number_density = self.absimg.phase_space_density[0]
        lambda_db = self.absimg.phase_space_density[1]


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
                {expansion_time * 1e3:.2f} ms &nbsp;
                <span style="font-weight:bold">Sigma:</span>\
                ({sigmax:.2f}, {sigmay:.2f}) mm<br>
                <span style="color:#CCC"><b>R-squared:</b>\
                {r_squared:.2f}</span>
                <span style="font-weight:bold">Centroid:</span>\
                ({centroid_x:.2f}, {centroid_y:.2f}) px
                <span style="font-weight:bold">λ_dB:</span>\
                {lambda_db:.2f} nm &nbsp;
                <span style="font-weight:bold">n:</span>\
                {number_density:.2f} m^-3 &nbsp;
                <span style="font-weight:bold">PSD:</span>\
                {PSD:.2f} m^-3 &nbsp;

            </div>"""
        )

    def update_schedule(self, mod) -> None:
        self.update()

        text = "<b>Running:</b>\t---"
        for _key, value in self.client.schedule.items():
            if value["status"] == "running":
                text = f"<b>Running:</b>\t{value['expid']['class_name']}"
        self.schedule_text.setText(text)

    def update_DLCProState(self) -> None:
        """Update the DLCPro state display using cached data from the client."""
        # First check if dlcpro service is connected
        dlcpro_service = self.client.services.get("dlcpro")
        if not dlcpro_service or dlcpro_service.state.name != "CONNECTED":
            # Update UI to show disconnected state
            self.dlc_status_label.setText(
                "<span style='color:red;'>DLCPro: Disconnected</span>"
            )
            self.dlc_outer_frame.setStyleSheet("background-color: #ffe8e8;")
            return

        # Check if we have cached data in the client
        dlcpro_cache = self.client.get_dlcpro_cache()
        if not dlcpro_cache:
            # If fetch is in progress, show connecting state
            status = "Connecting..." if self.client.is_dlcpro_fetching() else "No Data"
            self.dlc_status_label.setText(
                f"<span style='color:orange;'>DLCPro: {status}</span>"
            )
            self.dlc_outer_frame.setStyleSheet("background-color: #fff8e0;")
            return

        # Get emission and connection states from cache
        emission_enabled: bool = self.client.get_dlcpro_data("emission", False)
        emission_button_enabled: bool = self.client.get_dlcpro_data(
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
        # Get service state directly from services dictionary instead of connection_status
        dlcpro_service = self.client.services.get("dlcpro")

        if dlcpro_service and dlcpro_service.state.name == "CONNECTED":
            conn_color = "black"
        elif dlcpro_service and dlcpro_service.state.name == "CONNECTING":
            conn_color = "orange"
        else:  # BACKOFF or None
            conn_color = "red"

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
        """Update a single laser's display elements using cached data from client."""
        laser_prefix = f"laser{laser_num}"

        # Get laser data from client cache
        laser_enabled = self.client.get_dlcpro_data(f"{laser_prefix}:enabled", False)
        scan_enabled = self.client.get_dlcpro_data(
            f"{laser_prefix}:scan:enabled", False
        )
        emission_enabled = self.client.get_dlcpro_data("emission", False)
        dl_current = self.client.get_dlcpro_data(
            f"{laser_prefix}:dl:cc:current_set", 0.0
        )
        amp_current = self.client.get_dlcpro_data(
            f"{laser_prefix}:amp:cc:current_set", 0.0
        )
        lock_enabled = self.client.get_dlcpro_data(
            f"{laser_prefix}:dl:lock:lock_enabled", True
        )
        label = self.client.get_dlcpro_data(
            f"{laser_prefix}:label", f"Laser {laser_num}"
        )

        # Determine state and style the laser label
        is_active = emission_enabled and laser_enabled

        # Update the label with color indicating enabled/disabled state
        self.dlc_frames[laser_num - 1]["name"].setText(f"<b>{label}</b>")

        # Determine lock status text including scanning information
        if lock_enabled:
            lock_state = DeviceState.LOCKED
            lock_text = DeviceState.LOCKED.value
        else:
            lock_state = DeviceState.UNLOCKED
            lock_text = DeviceState.UNLOCKED.value
        lock_text += " (Scan)" if scan_enabled else ""

        # Update display
        self._update_device_display(
            "dlc",
            laser_num - 1,
            (DeviceState.ENABLED if is_active else DeviceState.DISABLED),
            f"Laser: {dl_current:.1f} mA",
            amp_current_text=f"Amp: {amp_current:.1f} mA",
            lock_state=lock_state,
            lock_text=lock_text,
        )

    def _update_laser_plot(self, laser_num):
        """Update the laser spectrum plot using cached data from client."""
        laser_prefix = f"laser{laser_num}"
        idx = laser_num - 1

        # Get canvas and axes
        canvas = self.dlc_frames[idx]["spectrum_canvas"]
        axes = self.dlc_frames[idx]["spectrum_axes"]
        axes.clear()

        # Only update if signal is available
        if not self.client.get_dlcpro_data(f"{laser_prefix}:scope:channel1:signal"):
            return

        # Get the spectrum data
        scope_data = extract_float_arrays(
            "xyY", self.client.get_dlcpro_data(f"{laser_prefix}:scope:data")
        )
        raw_lock_candidates = self.client.get_dlcpro_data(
            f"{laser_prefix}:dl:lock:candidates"
        )
        lock_candidates = extract_lock_points("clt", raw_lock_candidates)
        lock_state = extract_lock_state(raw_lock_candidates)

        # Get background data
        background_data = extract_float_arrays(
            "xy",
            self.client.dlcpro.get(f"{laser_prefix}:dl:lock:background_trace"),
        )

        # Plot background
        LOCK_STATE_LOCKED = 5  # 'Locked' state
        if lock_state == LOCK_STATE_LOCKED and len(background_data.get("x", [])) > 0:
            axes.plot(
                background_data["x"],
                background_data["y"],
                linestyle="solid",
                color="k",
                zorder=0,
                linewidth=1.0,
            )

        # Get current data limits (including both scope and background data)
        all_x_data = list(scope_data["x"])
        all_y_data = list(scope_data["y"])

        # Include background data if available and being plotted
        if lock_state == LOCK_STATE_LOCKED and len(background_data.get("x", [])) > 0:
            all_x_data.extend(background_data["x"])
            all_y_data.extend(background_data["y"])

        current_x_min = min(all_x_data) - 1e-6
        current_x_max = max(all_x_data) + 1e-6
        current_y_min = min(all_y_data) - 1e-6
        current_y_max = max(all_y_data) + 1e-6

        # Check if current data covers less than 50% of total limits
        current_x_range = current_x_max - current_x_min
        current_y_range = current_y_max - current_y_min
        total_x_range = (
            self.dlc_frames[idx]["x_lim"][1] - self.dlc_frames[idx]["x_lim"][0]
        )
        total_y_range = (
            self.dlc_frames[idx]["y_lim"][1] - self.dlc_frames[idx]["y_lim"][0]
        )

        # Reset limits if current data covers less than 50% of total limits or if limits are not initialized
        if (
            total_x_range == 0
            or total_y_range == 0
            or current_x_range / total_x_range < 0.55
            or current_y_range / total_y_range < 0.55
        ):
            self.dlc_frames[idx]["x_lim"] = [current_x_min, current_x_max]
            self.dlc_frames[idx]["y_lim"] = [current_y_min, current_y_max]
        else:
            # Update limits monotonically
            self.dlc_frames[idx]["x_lim"] = [
                min(self.dlc_frames[idx]["x_lim"][0], current_x_min),
                max(self.dlc_frames[idx]["x_lim"][1], current_x_max),
            ]
            self.dlc_frames[idx]["y_lim"] = [
                min(self.dlc_frames[idx]["y_lim"][0], current_y_min),
                max(self.dlc_frames[idx]["y_lim"][1], current_y_max),
            ]

        # Plot main spectrum data
        self._plot_spectrum_data(axes, scope_data, lock_candidates, lock_state)

        # Calculate x and y ranges
        x_range = self.dlc_frames[idx]["x_lim"][1] - self.dlc_frames[idx]["x_lim"][0]
        y_range = self.dlc_frames[idx]["y_lim"][1] - self.dlc_frames[idx]["y_lim"][0]

        # Add 5% padding to both sides
        padded_x_min = self.dlc_frames[idx]["x_lim"][0] - 0.05 * x_range
        padded_x_max = self.dlc_frames[idx]["x_lim"][1] + 0.05 * x_range
        padded_y_min = self.dlc_frames[idx]["y_lim"][0] - 0.05 * y_range
        padded_y_max = self.dlc_frames[idx]["y_lim"][1] + 0.05 * y_range

        # Set the padded limits
        axes.set_xlim([padded_x_min, padded_x_max])
        axes.set_ylim([padded_y_min, padded_y_max])

        axes.patch.set_alpha(0)

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
                color="blue",
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
                color="black",
                markerfacecolor="none",
                zorder=3,
            )

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
                STATE_MAPPING = {val.value: val for val in DeviceState}
                STATE_MAPPING.update(
                    {
                        DeviceState.ENABLED.value: (
                            DeviceState.LOW_POWER
                            if output_power < LOW_POWER_THRESHOLD
                            else DeviceState.ENABLED
                        )
                    }
                )

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
        lock_text=None,
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
            frame["state"].setText("")  # Clear the state text
            frame["dl_current"].setText(value_text)
            if amp_current_text:
                frame["amp_current"].setText(amp_current_text)
            if lock_state:
                # Use custom lock text if provided, otherwise use the enum value
                frame["lock"].setText(lock_text if lock_text else lock_state.value)

            styles = DEVICE_STYLES[state]
            # No need to style state text anymore
            frame["frame"].setStyleSheet(styles["frame"])

            if lock_state:
                lock_styles = DEVICE_STYLES[lock_state]
                frame["lock"].setStyleSheet(lock_styles["state"])

    def saveDatasets(self):
        data = {key: val[1] for key, val in self.client.datasets.items()}
        print("Saving datasets, type: ", type(data))
        np.save("datasets.npy", data)

    def handle_service_state_change(self, service_name, old_state, new_state):
        """Handle state changes for services"""
        logging.info(
            f"Service {service_name} changed from {old_state.name} to {new_state.name}"
        )

        # Update UI immediately on state change
        self.update_connection_status()

        # If a service just connected, refresh relevant UI
        if old_state.name != "CONNECTED" and new_state.name == "CONNECTED":
            if service_name == "datasets":
                # Refresh datasets display
                self.update()
            elif service_name == "dlcpro":
                # Refresh DLCPro display
                self.update_DLCProState()
            elif service_name == "schedule":
                # Refresh schedule display
                self.update_schedule(None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    APP = QApplication(sys.argv)
    APP.setStyle("Fusion")

    loop = QEventLoop(APP)
    asyncio.set_event_loop(loop)

    main_window = MainWindow(app=APP)

    main_window.show()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Shutting down...")
    finally:
        APP.shutdown = True
        print("Shutting down ARTIQ Monitor...")
        # Ensure clean shutdown
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
