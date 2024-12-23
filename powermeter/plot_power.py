import sys, os
from time import perf_counter,sleep,time
import argparse
import numpy as np
import pyqtgraph as pg

from ThorlabsPM100 import ThorlabsPM100
from usbtmc import USBTMC

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QSpinBox,
    QComboBox,
)
from PyQt6.QtGui import QIcon, QPalette, QColor, QFontDatabase
from PyQt6.QtCore import Qt
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import pyqtSignal as Signal


# Now use a palette to switch to dark colors:
palette = QPalette()
palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(0, 0, 0))
palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
class FrameCounter(QtCore.QObject):
    sigFpsUpdate = Signal(object)

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

    def __init__(self, powermeter: ThorlabsPM100 = None):
        super().__init__()

        self.pm = powermeter

        self.timeData = []
        self.powerData = []

        self.initUI()

    def update(self):
        now = time()

        # if the region spans the last time point, extend it to the new time point
        minX, maxX = self.region.getRegion()
        if self.timeData:
            if minX < self.timeData[0]:
                minX = self.timeData[0]
                maxX = now
            elif maxX >= self.timeData[-1]:
                maxX = now

        self.timeData.append(now)
        self.powerData.append(self.pm.read if self.pm is not None else np.random.rand())

        # only plot at max 1000 points so downsample them with the relevant stride
        numvals = len(self.timeData)
        stride = numvals // 1000 + 1
        zoom = (self.timeData[-1] - self.timeData[0]) / (maxX - minX)
        stride2 = int(stride / (zoom + 0.001)) + 1
        self.maincurve.setData(self.timeData[::stride2], self.powerData[::stride2])
        self.timecurve.setData(self.timeData[::stride], self.powerData[::stride])

        self.region.setBounds([self.timeData[0], self.timeData[-1]])
        self.region.setRegion([minX, maxX])

        self.current_power.setText(f"{self.powerData[-1]*1e3:.2f} mW")
        self.numvals.setText(f"# readings: {numvals}")
        self.framecnt.update()

    # callback to reset region
    def mouseDoubleClickEvent(self, event):
        if self.timeData:
            self.region.setRegion([self.timeData[0], self.timeData[-1]])

    def create_mainplot(self):
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
            pen=pg.mkPen("w", width=2),
            autoDownsample=True,
            downsampleMethod="peak",
            clipToView=True,
            skipFiniteCheck=True,
        )

        return mainplot, maincurve

    def create_timeplot(self, mainplot):
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
            pen=pg.mkPen("w", width=1),
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

    def set_wavelength(self, wavelength):
        if self.pm is not None:
            self.pm.sense.correction.wavelength = wavelength
            self.wavelength.setMinimum(self.pm.sense.correction.minimum_wavelength)
            self.wavelength.setMaximum(self.pm.sense.correction.maximum_wavelength)
        else:
            print("Cannot set wavelength without a powermeter")

    def set_average(self, average):
        if self.pm is not None:
            self.pm.sense.average.count = average
        else:
            print("Cannot set average without a powermeter")

    def initUI(self):
        self.setWindowTitle("Powermeter Plot")
        self.setGeometry(100, 100, 800, 600)
        pg.setConfigOption("background", "#535353")
        pg.setConfigOption("foreground", "#ffffff")
        # pg.setConfigOptions(antialias=True)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.setStyleSheet("color: white;")

        # Wavelength
        self.wavelength = QSpinBox()
        self.wavelength.setMinimum(400)
        self.wavelength.setMaximum(1100)
        self.wavelength.setValue(800)
        self.wavelength.setSuffix(" nm")
        self.wavelength.valueChanged.connect(self.set_wavelength)

        # sample rate
        self.samplerate = QComboBox()
        self.samplerate.addItem("0.1 Hz", 10000)
        self.samplerate.addItem("1 Hz", 1000)
        self.samplerate.addItem("10 Hz", 100)
        self.samplerate.addItem("100 Hz", 10)
        self.samplerate.addItem("Max", 0)
        self.samplerate.setCurrentIndex(2)
        self.samplerate.currentIndexChanged.connect(
            lambda: self.timer.setInterval(self.samplerate.currentData())
        )

        # averaging
        self.average = QSpinBox()
        self.average.setMinimum(1)
        self.average.setMaximum(100)
        self.average.setValue(10)
        self.average.valueChanged.connect(self.set_average)

        # start/stop button
        self.startstop = QPushButton("STOP")
        self.startstop.setStyleSheet(
            "color: red; font-weight: bold"
        )
        def startstop():
            if not self.startstop.isChecked():
                self.timer.start()
                self.startstop.setStyleSheet("color: red; font-weight: bold")
                self.startstop.setText("STOP")
            else:
                self.timer.stop()
                self.startstop.setStyleSheet("background-color: red; color: white; font-weight: bold")
                self.startstop.setText("STOPPED")

        self.startstop.setCheckable(True)
        self.startstop.setChecked(False)
        self.startstop.clicked.connect(startstop)

        # data
        self.current_power = QLabel("W")
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(60)
        font.setBold(True)
        self.current_power.setFont(font)
        self.reset = QPushButton("Reset")
        def reset():
            self.timeData = []
            self.powerData = []
            self.maincurve.setData(self.timeData, self.powerData)
            self.timecurve.setData(self.timeData, self.powerData)
            self.current_power.setText("W")
            self.numvals.setText("# readings: 0")
        self.reset.clicked.connect(lambda: reset())

        # layout
        """
        wavelength : val     |
        ---------------------      Current Power
        sample rate : val    | 
        --------------------------------------------
        averaging : val      | Stop/Start | Reset
        """
        main = QGridLayout()
        main.setColumnStretch(2, 5)
        main.setColumnStretch(0, 2)
        main.setColumnStretch(1, 1)
        main.addWidget(QLabel("Wavelength:"), 0, 0)
        main.addWidget(self.wavelength, 0, 1)
        main.addWidget(QLabel("Sample rate:"), 1, 0)
        main.addWidget(self.samplerate, 1, 1)
        main.addWidget(QLabel("Averaging:"), 2, 0)
        main.addWidget(self.average, 2, 1)
        main.addWidget(self.current_power, 0, 2, 4, 1,Qt.AlignmentFlag.AlignCenter)
        main.addWidget(self.startstop, 3, 0)
        main.addWidget(self.reset, 3, 1)

        self.layout.addLayout(main)
        # plot of power
        self.mainplot, self.maincurve = self.create_mainplot()
        self.layout.addWidget(self.mainplot)
        self.timeplot, self.timecurve = self.create_timeplot(mainplot=self.mainplot)
        self.layout.addWidget(self.timeplot)
        self.timeplot.setMaximumHeight(self.mainplot.height() // 5)

        # update plot every 100ms
        self.timer = pg.QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(self.samplerate.currentData())

        # diagnostic stats
        self.framecnt = FrameCounter()

        def updatefps(fps):
            self.fps.setText(f"{fps:.1f} Hz")

        self.framecnt.sigFpsUpdate.connect(lambda fps: updatefps(fps))
        statsHBox = QHBoxLayout()
        self.fps = QLabel("0 Hz")
        self.fps.setStyleSheet("QLabel { color : gray; }")
        statsHBox.addWidget(self.fps)
        statsHBox.addStretch()
        self.numvals = QLabel("# readings: 0")
        self.numvals.setStyleSheet("QLabel { color : gray; }")
        statsHBox.addWidget(self.numvals)
        self.layout.addLayout(statsHBox)

        self.show()


def launchWindow(device):
    app = QApplication(sys.argv)
    # Set a nice icon
    app.setWindowIcon(
        QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    app.setStyle("Fusion")
    app.setPalette(palette)
    app.setApplicationName("Power Meter")

    if device is not None:
        power_meter = init_powermeter(device)
    else:
        power_meter = None

    window = PowerMeterPlot(powermeter=power_meter)
    window.show()
    sys.exit(app.exec())

def init_powermeter(device):
    # check if the path exists and if not retry with exponential backoff
    backoff = 1
    while not os.path.exists(device):
        print(f"Device  {device} not found, retrying in {backoff} seconds...")
        sleep(backoff)
        backoff *= 2
        if backoff > 60:
            print("Device not found, exiting...")
            sys.exit(1)

    inst = USBTMC(device)
    power_meter = ThorlabsPM100(inst = inst)
    power_meter.system.beeper.immediate()

    print("Measurement type :", power_meter.getconfigure)
    print("Current value    :", power_meter.read)
    print("Wavelength       :", power_meter.sense.correction.wavelength)
    print("Power range limit:", power_meter.sense.power.dc.range.upper)
    print("Set range auto...")
    power_meter.sense.power.dc.range.auto = "ON"
    print("Set bandwidth to High")
    power_meter.input.pdiode.filter.lpass.state = 0

    return power_meter

if __name__ == "__main__":
    # parse command line arguments for the device path
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", help="Display all devices", action="store_true")
    parser.add_argument("--device", help="USB device path", default="/dev/usbtmc1")
    parser.add_argument("--fake", help="Use fake powermeter", action="store_true")
    args = parser.parse_args()

    if args.fake:
        launchWindow(None)

    if args.all:
        # spin off separate processes for each device in /dev/usbtmc*to increase robustness
        from multiprocessing import Process

        processes = {}

        # start the main loop
        while True:
            # check if any of the processes have finished and if so, remove them
            for device in list(processes.keys()):
                if not processes[device].is_alive():
                    print(f"Process for {device} has finished")
                    del processes[device]

            # start any new powermeters
            for device in os.listdir("/dev"):
                if "usbtmc" in device and device not in processes:
                    print(f"Starting process for {device}")
                    processes[device] = Process(
                        target=launchWindow, args=(f"/dev/{device}",)
                    )
                    processes[device].start()

            sleep(1)
    else:
        print(f"Starting process for {args.device}")
        launchWindow(args.device)
