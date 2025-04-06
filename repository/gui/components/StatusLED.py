from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtWidgets import QWidget, QLabel, QHBoxLayout, QApplication, QVBoxLayout
from PyQt5.QtGui import QPainter, QColor, QPainterPath, QRadialGradient, QPen, QPixmap


class LedWidget(QWidget):
    """LED indicator widget with efficient rendering via pixmap caching"""

    def __init__(self, parent=None, color="#808080", size=16):
        super().__init__(parent)
        self.setFixedSize(QSize(size, size))
        self._color = color
        self._brightness = 1.0
        self._pixmap_cache = {}  # Cache for rendered LEDs
        self._current_pixmap = None
        self._render_led()  # Pre-render on initialization

    def _render_led(self):
        """Pre-render the LED to a cached pixmap"""
        cache_key = (self._color, self._brightness)

        if cache_key in self._pixmap_cache:
            self._current_pixmap = self._pixmap_cache[cache_key]
            return

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Apply brightness to base color
        base_color = QColor(self._color)
        dim_color = QColor(
            *(
                int(c * self._brightness)
                for c in [base_color.red(), base_color.green(), base_color.blue()]
            )
        )

        # Create gradient for subtle 3D effect
        radius = min(self.width(), self.height()) / 2
        center_x, center_y = self.width() / 2, self.height() / 2

        gradient = QRadialGradient(
            center_x - radius / 4, center_y - radius / 4, radius * 2, center_x, center_y
        )
        gradient.setColorAt(0, dim_color.lighter(120))
        gradient.setColorAt(0.5, dim_color)
        gradient.setColorAt(1, dim_color.darker(115))
        painter.setBrush(gradient)

        # Add thin black outline
        painter.setPen(QPen(QColor(0, 0, 0, 120), 0.5))
        painter.drawEllipse(0, 0, self.width() - 1, self.height() - 1)

        # Add highlight for subtle 3D effect
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        highlight_path = QPainterPath()
        highlight_path.addEllipse(
            self.width() * 0.3,
            self.height() * 0.3,
            self.width() * 0.25,
            self.height() * 0.25,
        )
        painter.drawPath(highlight_path)
        painter.end()

        # Store in cache and set as current
        self._pixmap_cache[cache_key] = pixmap
        self._current_pixmap = pixmap

        # Limit cache size
        if len(self._pixmap_cache) > 10:
            del self._pixmap_cache[list(self._pixmap_cache.keys())[0]]

    def paintEvent(self, event):
        """Draw the cached pixmap"""
        if not self._current_pixmap:
            self._render_led()
        QPainter(self).drawPixmap(0, 0, self._current_pixmap)

    def set_color(self, color):
        """Set LED color"""
        self._color = color
        self._render_led()
        self.update()

    def set_brightness(self, brightness):
        """Set LED brightness"""
        self._brightness = max(0.0, min(1.0, brightness))
        self._render_led()
        self.update()


class StatusLED(QWidget):
    """Configurable status indicator with optional label and blinking"""

    # Common status colors
    COLOR_GREEN = "#00FF00"  # Ready/OK
    COLOR_RED = "#FF0000"  # Error/Fault
    COLOR_AMBER = "#FFBF00"  # Warning/Busy
    COLOR_BLUE = "#0080FF"  # Process running
    COLOR_GRAY = "#808080"  # Inactive/Off

    def __init__(self, parent=None, color=COLOR_GRAY, size=16, label=None, blink=False):
        super().__init__(parent=parent)
        self._color = color
        self._brightness = 1.0
        self._active = True
        self._blink_enabled = False
        self._blink_interval = 500
        self._timer = None

        # Setup layout
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.led_widget = LedWidget(parent=self, color=color, size=size)
        layout.addWidget(self.led_widget)

        if label:
            self.label = QLabel(label)
            layout.addWidget(self.label)

        self.setLayout(layout)

        if blink:
            self.set_blinking(True)

    def _toggle_brightness(self):
        """Toggle LED brightness for blinking effect"""
        new_brightness = 0.4 if self._brightness > 0.4 else 1.0
        self._brightness = new_brightness
        self.led_widget.set_brightness(new_brightness)

    def set_color(self, color):
        """Set the LED color"""
        if self._color != color:
            self._color = color
            self.led_widget.set_color(color)

    def set_blinking(self, enabled, interval=None):
        """Enable or disable LED blinking"""
        # Skip if no change
        if enabled == self._blink_enabled and (
            interval is None or interval == self._blink_interval
        ):
            return

        self._blink_enabled = enabled
        if interval:
            self._blink_interval = interval

        # Create timer if needed
        if enabled:
            if self._timer is None:
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._toggle_brightness)
            self._timer.start(self._blink_interval)
        elif self._timer is not None:
            self._timer.stop()
            self.led_widget.set_brightness(1.0)
            self._brightness = 1.0

    def set_label(self, text):
        """Update the label text"""
        if hasattr(self, "label"):
            self.label.setText(text)

    def set_active(self, active):
        """Set the LED active/inactive state"""
        if self._active != active:
            self._active = active
            if not active:
                self.led_widget.set_brightness(0.3)
                self._brightness = 0.3
                if self._timer:
                    self._timer.stop()
            else:
                self.led_widget.set_brightness(1.0)
                self._brightness = 1.0


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)

    widget = QWidget()
    widget.setWindowTitle("Status LEDs Example")
    layout = QVBoxLayout()

    # Create examples
    layout.addWidget(StatusLED(color=StatusLED.COLOR_GREEN, label="Ready"))
    layout.addWidget(StatusLED(color=StatusLED.COLOR_RED, label="Error", blink=True))
    layout.addWidget(StatusLED(color=StatusLED.COLOR_AMBER, label="Busy"))
    layout.addWidget(StatusLED(color=StatusLED.COLOR_BLUE, label="Running"))
    layout.addWidget(StatusLED(color=StatusLED.COLOR_GRAY, label="Offline"))

    purple_led = StatusLED(color="#8A2BE2", label="Custom Color")
    layout.addWidget(purple_led)
    purple_led.set_blinking(True, 1000)  # Blink every second

    layout.addStretch(1)
    widget.setLayout(layout)
    widget.resize(200, 300)
    widget.show()

    sys.exit(app.exec_())
