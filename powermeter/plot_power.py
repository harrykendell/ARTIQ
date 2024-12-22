"""
Window for powermeter data plotting

Continually polls for poweremeters and connects to them, then opens a window for it

Each window shows the whole timeseries at the bottom and a zoomed in version at the top selected by the sliders
There is also a current power reading, mean power reading over the selected range, and standard deviation of the selected range
    - Wavelength selector

"""

import sys, os
import time
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QSpinBox,
    QComboBox,)
from PyQt5 import QtGui
import numpy as np


from ThorlabsPM100 import ThorlabsPM100
import pyqtgraph as pg

from pyqtgraph.Qt import QtCore
from time import perf_counter


class FrameCounter(QtCore.QObject):
    sigFpsUpdate = QtCore.Signal(object)

    def __init__(self, interval=1000):
        super().__init__()
        self.count = 0
        self.last_update = 0
        self.interval = interval

    def update(self):
        self.count += 1

        if self.last_update == 0:
            self.last_update = perf_counter()
            self.startTimer(self.interval)

    def timerEvent(self, evt):
        now = perf_counter()
        elapsed = now - self.last_update
        fps = self.count / elapsed
        self.last_update = now
        self.count = 0
        self.sigFpsUpdate.emit(fps)

class PowerMeterPlot(QWidget):

    def __init__(self):
        super().__init__()

        self.timeData = []
        self.powerData = []

        self.initUI()

    def update(self):
        now = time.time()

        # if the region spans the last time point, extend it to the new time point
        minX, maxX = self.region.getRegion()
        if self.timeData:
            if minX < self.timeData[0]:
                minX = self.timeData[0]
                maxX = now
            elif maxX >= self.timeData[-1]:
                maxX = now

        self.timeData.append(now)
        self.powerData.append(np.random.normal())

        # only plot at max 1000 points so downsample them with the relevant stride
        numvals = len(self.timeData)
        stride = numvals // 1000 + 1
        zoom = (self.timeData[-1] - self.timeData[0]) / (maxX - minX)
        stride2 = int(stride / zoom + 0.001) + 1
        self.maincurve.setData(self.timeData[::stride2], self.powerData[::stride2])
        self.timecurve.setData(self.timeData[::stride], self.powerData[::stride])

        self.region.setBounds([self.timeData[0], self.timeData[-1]])
        self.region.setRegion([minX, maxX])

        self.numvals.setText(f"# readings: {numvals}")
        self.framecnt.update()

    # callback to reset region
    def mouseDoubleClickEvent(self, event):
        if self.timeData:
            self.region.setRegion([self.timeData[0], self.timeData[-1]])

    def mainplot(self):
        # zoomed plot of power
        mainplot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.layout.addWidget(mainplot)

        mainplot.setMouseEnabled(x=False, y=False)
        mainplot.enableAutoRange(x=True, y=True)
        mainplot.setAutoVisible(x=True, y=True)
        mainplot.setLabel("left", "Power", units="W")
        mainplot.hideButtons()

        maincurve = mainplot.plot(
            self.timeData,
            self.powerData,
            pen=pg.mkPen("k", width=3),
            autoDownsample=True,
            downsampleMethod="peak",
            clipToView=True,
            skipFiniteCheck=True,
        )

        return mainplot, maincurve

    def timeplot(self, mainplot):
        # total time series plot
        timeplot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.layout.addWidget(timeplot)

        timeplot.mouseDoubleClickEvent = self.mouseDoubleClickEvent
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        timeplot.addItem(self.region, ignoreBounds=False)
        timeplot.hideAxis("left")
        timeplot.setMouseEnabled(x=False, y=False)
        timeplot.enableAutoRange(x=True, y=True)

        self.timecurve = timeplot.plot(
            self.timeData,
            self.powerData,
            pen=pg.mkPen("k", width=1),
            autoDownsample=True,
            downsampleMethod="peak",
            clipToView=True,
            skipFiniteCheck=True,
        )

        def updateMainwhenRegionChanges():
            # print("updated main: ", self.region.getRegion())
            minX, maxX = self.region.getRegion()
            mainplot.setXRange(minX, maxX, padding=0)

        self.region.sigRegionChanged.connect(updateMainwhenRegionChanges)

        return timeplot, self.timecurve

    def initUI(self):
        self.setWindowTitle("Powermeter Plot")
        self.setGeometry(100, 100, 800, 600)
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")
        # pg.setConfigOptions(antialias=True)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # controls
        # Wavelength
        self.layout.addWidget(QLabel("Wavelength"))
        self.wavelength = QSpinBox()
        self.wavelength.setMinimum(400)
        self.wavelength.setMaximum(1100)
        self.wavelength.setValue(780)
        self.wavelength.setSuffix(" nm")
        self.layout.addWidget(self.wavelength)

        # powermeter selection
        self.layout.addWidget(QLabel("Select powermeter: -"))

        # sample rate
        self.layout.addWidget(QLabel("Sample rate:"))
        self.samplerate = QComboBox()
        self.samplerate.addItem("0.1 Hz")
        self.samplerate.addItem("1 Hz")
        self.samplerate.addItem("10 Hz")
        self.samplerate.addItem("100 Hz")
        self.samplerate.setCurrentIndex(2)
        self.layout.addWidget(self.samplerate)
        
        # averaging
        self.layout.addWidget(QLabel("Averaging"))

        # start/stop button
        self.layout.addWidget(QLabel("Start/Stop sampling: "))
        self.startstop = QPushButton("Start")
        self.startstop.setCheckable(True)
        self.startstop.setChecked(False)
        self.layout.addWidget(self.startstop)

        # data
        self.layout.addWidget(QLabel("Current power: "))

        # plot of power
        self.mainplot, self.maincurve = self.mainplot()
        self.layout.addWidget(self.mainplot)
        self.timeplot, self.timecurve = self.timeplot(mainplot=self.mainplot)
        self.layout.addWidget(self.timeplot)
        self.timeplot.setMaximumHeight(self.mainplot.height() // 5)

        # update plot every 100ms
        self.timer = pg.QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(0)

        # diagnostic stats
        self.framecnt = FrameCounter()

        def updatefps(fps):
            self.fps.setText(f"{fps:.1f} fps")

        self.framecnt.sigFpsUpdate.connect(lambda fps: updatefps(fps))
        statsHBox = QHBoxLayout()
        self.fps = QLabel("0 fps")
        self.fps.setStyleSheet("QLabel { color : gray; }")
        statsHBox.addWidget(self.fps)
        statsHBox.addStretch()
        self.numvals = QLabel("# readings: 0")
        self.numvals.setStyleSheet("QLabel { color : gray; }")
        statsHBox.addWidget(self.numvals)
        self.layout.addLayout(statsHBox)

        self.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = PowerMeterPlot()
    sys.exit(app.exec_())
