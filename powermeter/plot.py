import os, glob, sys
from time import perf_counter,sleep,time
import argparse
from serial.tools.list_ports import comports
import multiprocessing as mp
import pyqtgraph as pg

from ThorlabsPM100 import ThorlabsPM100
from usbtmc import USBTMC

from PyQt6.QtWidgets import (
    QMainWindow,
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QSpinBox,
    QComboBox,
)
from PyQt6.QtGui import QIcon, QFontDatabase
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import Qt, QTimer, pyqtSignal as Signal

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

    def __init__(self, powermeter: ThorlabsPM100 = None, device: str = None):
        super().__init__()

        self.pm = powermeter
        self.device = device

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

        # check if we can read from pm and if not stop the timer
        try:
            self.timeData.append(now)
            self.powerData.append(self.pm.read)
        except:
            self.timer.stop()
            self.startstop.setStyleSheet("background-color: red; color: white; font-weight: bold")
            self.startstop.setText("Disconnected")
            return

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
        # format with commas
        self.numvals.setText(f"# readings: {numvals:,}")
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
            pen=pg.mkPen("k", width=2),
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

    def set_wavelength(self, wavelength):
        if self.pm is not None:
            self.pm.sense.correction.wavelength = wavelength
            self.wavelength.setMinimum(int(self.pm.sense.correction.minimum_wavelength))
            self.wavelength.setMaximum(int(self.pm.sense.correction.maximum_wavelength))
        else:
            print("Cannot set wavelength without a powermeter")

    def set_average(self, average):
        if self.pm is not None:
            self.pm.sense.average.count = average
        else:
            print("Cannot set average without a powermeter")

    def initUI(self):
        self.setWindowTitle(f"Powermeter Plot ({self.device})")
        self.setGeometry(100, 100, 800, 600)
        pg.setConfigOption("background", "#eeeeee")
        pg.setConfigOption("foreground", "#000000")
        # pg.setConfigOptions(antialias=True)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        # self.setStyleSheet("color: white;")

        # Wavelength
        self.wavelength = QSpinBox()
        self.wavelength.setMinimum(400)
        self.wavelength.setMaximum(1100)
        self.wavelength.setValue(780)
        self.wavelength.setSuffix(" nm")
        self.wavelength.valueChanged.connect(self.set_wavelength)
        self.set_wavelength(780)

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

def launchPowerMeterPlot(device):
    if device is not None:
        power_meter = initPowermeter(device)
    else:
        power_meter = None

    window = PowerMeterPlot(powermeter=power_meter, device=device)
    window.show()
    window.setWindowIcon(
        QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    return window

def forkPlot(device):
    app = QApplication([])
    app.setWindowIcon(
        QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    app.setStyle("Fusion")

    launchPowerMeterPlot(device)

    app.exec()

def initPowermeter(device, backoff = True):
    # check if the path exists and if not retry with exponential backoff
    backoff = 1
    while not os.path.exists(device):
        print(f"Device  {device} not found, retrying in {backoff} seconds...")
        backoff *= 2
        if backoff > 60 or not backoff:
            print("Device not found, exiting...")
            return
        sleep(backoff)

    inst = USBTMC(device)
    power_meter = ThorlabsPM100(inst = inst)
    power_meter.system.beeper.immediate()
    power_meter.sense.power.dc.range.auto = "ON"
    power_meter.input.pdiode.filter.lpass.state = 0
    power_meter.sense.correction.wavelength = 780

    return power_meter

class PowerMeterTracker(QMainWindow):
    def __init__(self):
        super().__init__()
        self.windows = {}
        self.initUI()

    def initUI(self):
        # main list with a start/stop button on each PM listed in /dev/usbtmc*
        # a shutdown button to close all windows
        # a timer to keep the active powermeters up to date with the selection in qlistwidget

        self.setWindowTitle("Power Meter Tracker")

        self.listWidget = QListWidget(self)
        self.shutdownButton = QPushButton("Shutdown", self)
        self.shutdownButton.clicked.connect(self.shutdown_program)

        layout = QVBoxLayout()
        layout.addWidget(self.listWidget)
        layout.addWidget(self.shutdownButton)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.main_loop)
        self.timer.start(1000)

    def shutdown_program(self):
        print("Shutting down program")
        for item in self.listWidget.findItems("*", Qt.MatchFlag.MatchWildcard):
            if item.data is not None:
                item.data.kill()
        QApplication.instance().quit()

    class PowerMeterListItem(QListWidgetItem):
        def __init__(self, device, parent=None):
            super().__init__(parent)

            self.setText(self.device)
            self.setFlags(self.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.setCheckState(Qt.CheckState.Unchecked)

            self.previous_state = self.checkState()

        def start(self):
            self.window = launchPowerMeterPlot(self.device)
            self.window.show()

        def stop(self):
            self.window.close()

    def item_state_changed(self, state):
        print("Item state changed")

    def main_loop(self):
        def add_device(dev):
            item = QListWidgetItem()
            item.setText(dev)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.data = None
            self.listWidget.addItem(item)

        # keep the active powermeters up to date with the selection in qlistwidget
        if sys.platform.startswith('win'):
            ports = [p.usb_description() for p in comports()]
        elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
            # this excludes your current terminal "/dev/tty"
            ports = glob.glob("/dev/usbtmc*")
        for dev in ports:
            # make sure all plugged in powermeters are listed
            items = self.listWidget.findItems(dev, Qt.MatchFlag.MatchExactly) 
            if items:
                # if the powermeter is checked, start it
                item = items[0]
                if item.checkState() == Qt.CheckState.Checked:
                    if item.data is None:
                        # item.data = launchPowerMeterPlot(f"/dev/{dev}")
                        item.data = mp.Process(target=forkPlot, args=(dev,))
                        print(f"Starting process for {dev}")
                        item.data.start()
                    elif not item.data.is_alive():
                        item.data.kill()
                        item.data=None
                        item.setCheckState(Qt.CheckState.Unchecked)
                elif item.data is not None:
                    item.data.kill()
                    item.data = None
            else: # if the powermeter is not listed, add it
                add_device(dev)

        # remove any powermeters that are not plugged in
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            if not os.path.exists(item.text()):
                self.listWidget.takeItem(i)

if __name__ == "__main__":
    mp.set_start_method("spawn")
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", help="Display all devices", action="store_true")
    parser.add_argument("--device", help="USB device path", default="/dev/usbtmc1")
    args = parser.parse_args()

    app = QApplication([])
    app.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png"))

    app.setStyle("Fusion")

    if args.all:
        window = PowerMeterTracker()
        window.show()
        window.setWindowIcon(QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png"))
    else:
        launchPowerMeterPlot(args.device)

    app.exec()
