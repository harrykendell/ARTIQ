"""
MIT License

Copyright (c) 2021 Parsa.py

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from PyQt5.QtCore import (
    Qt,
    QPoint,
    pyqtSlot,
    pyqtProperty,
    QPropertyAnimation,
    QEasingCurve,
)
from PyQt5.QtWidgets import QWidget, QCheckBox
from PyQt5.QtGui import QPainter, QColor


def take_closest(num, collection):
    return min(collection, key=lambda x: abs(x - num))


class SwitchCircle(QWidget):
    def __init__(
        self, parent, move_range: tuple, color, animation_curve, animation_duration
    ):
        super().__init__(parent=parent)
        self.color = color
        self.move_range = move_range
        self.animation = QPropertyAnimation(self, b"pos")
        self.animation.setEasingCurve(animation_curve)
        self.animation.setDuration(animation_duration)

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.HighQualityAntialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(0, 0, 16, 16)
        painter.end()

    def set_color(self, value):
        self.color = value
        self.update()

class Switch(QCheckBox):

    def __init__(
        self,
        parent=None,
        bg_color="gray",
        circle_color="#DDD",
        active_color="green",
        animation_curve=QEasingCurve.InOutExpo,
        animation_duration=50,
        checked: bool = False,
    ):
        super().__init__(parent=parent)
        self.setFixedSize(40, 20)
        self.bg_color = bg_color
        self.circle_color = circle_color
        self.animation_curve = animation_curve
        self.animation_duration = animation_duration
        self.__circle = SwitchCircle(
            self,
            (2, self.width() - 20),
            self.circle_color,
            self.animation_curve,
            self.animation_duration,
        )
        self.active_color = active_color
        if checked:
            self.__circle.move(self.width() - 20, 2)
            self.setChecked(True)
        elif not checked:
            self.__circle.move(3, 2)
            self.setChecked(False)
        self.animation = QPropertyAnimation(self.__circle, b"pos")
        self.animation.setEasingCurve(animation_curve)
        self.animation.setDuration(animation_duration)

    def start_animation(self, checked):
        self.animation.stop()
        self.animation.setStartValue(self.__circle.pos())
        if checked:
            self.animation.setEndValue(QPoint(self.width() - 20, self.__circle.y()))
            self.setChecked(True)
        if not checked:
            self.animation.setEndValue(QPoint(3, self.__circle.y()))
            self.setChecked(False)
        self.animation.start()

    def paintEvent(self, event):
        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.HighQualityAntialiasing)
        painter.setPen(Qt.NoPen)
        if not self.isChecked():
            painter.setBrush(QColor(self.bg_color))
            painter.drawRoundedRect(
                0, 0, self.width(), self.height(), self.height() / 2, self.height() / 2
            )
        elif self.isChecked():
            painter.setBrush(QColor(self.active_color))
            painter.drawRoundedRect(
                0, 0, self.width(), self.height(), self.height() / 2, self.height() / 2
            )

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def mousePressEvent(self, event):
        self.start_animation(not self.isChecked())

if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication([])

    window = QWidget()
    window.setWindowTitle("Switch Control")
    window.setGeometry(100, 100, 400, 200)

    layout = QVBoxLayout()

    switch = Switch()
    layout.addWidget(switch)

    window.setLayout(layout)

    window.show()

    app.exec_()
