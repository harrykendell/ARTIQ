import os, glob
from time import perf_counter, time, sleep
import multiprocessing as mp
import pyqtgraph as pg

# import depending on windows or linux
if os.name == "nt":
    from PM100_Windows import PM100D
else:
    from PM100_Linux import PM100D
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
    QFileDialog,
)
from PyQt6.QtGui import QIcon, QFontDatabase, QColor
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

    def __init__(self, powermeter: PM100D = None, device: str = None):
        super().__init__()

        self.pm = powermeter
        self.device = device

        self.timeData = []
        self.powerData = []

        self.initUI()

    def try_read_pm(self):
        try:
            if os.name == "nt":
                _, pow = self.pm.deviceNET.measPower()
            else:
                pow = self.pm.read
        except:
            self.timer.stop()
            self.startstop.setStyleSheet(
                "background-color: red; color: white; font-weight: bold"
            )
            self.startstop.setText("Disconnected")
            return None
        return pow

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
        pow = self.try_read_pm()
        if pow:
            self.timeData.append(now)
            self.powerData.append(pow)

        # given minX and maxX, crop down to only the relevant data
        i=0
        j=len(self.timeData)
        while self.timeData[i] < minX:
            i+=1
        if j>1:
            while self.timeData[j-1] > maxX:
                j-=1

        # only plot at max 1000 points so downsample them with the relevant stride
        numvals = j-i
        stride = len(self.timeData) // 1000 + 1
        stride2 = int(numvals // 1000 + 1)
        self.maincurve.setData(self.timeData[i:j:stride2], self.powerData[i:j:stride2])
        self.maxline.setValue(max(self.powerData))
        self.timecurve.setData(self.timeData[::stride], self.powerData[::stride])
        # automatically swap between uW and mW
        self.current_power.setText(
            f"{self.powerData[-1]*1e3:.2f} mW"
            if self.powerData[-1] > 1e-3
            else f"{self.powerData[-1]*1e6:.2f} uW"
        )
        # format with commas
        self.numvals.setText(f"# readings: {numvals:,}")

        self.region.setBounds([self.timeData[0], self.timeData[-1]])
        self.region.setRegion([minX, maxX])

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

        maxline = pg.InfiniteLine(
            pos=0,
            angle=0,
            movable=False,
            pen=pg.mkPen(QColor(20, 20, 200, 50), width=2),
        )
        mainplot.addItem(maxline)

        return maxline, mainplot, maincurve

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
            if os.name == "nt":
                self.pm.setWaveLength(wavelength)
                self.wavelength.setMinimum(int(self.pm.wavelengthMin))
                self.wavelength.setMaximum(int(self.pm.wavelengthMax))
            else:
                self.pm.sense.correction.wavelength = wavelength
                self.wavelength.setMinimum(
                    int(self.pm.sense.correction.minimum_wavelength)
                )
                self.wavelength.setMaximum(
                    int(self.pm.sense.correction.maximum_wavelength)
                )
        else:
            print("Cannot set wavelength without a powermeter")

    def set_average(self, average):
        if self.pm is not None:
            if os.name == "nt":
                print("Average not implemented on windows")
            else:
                self.pm.sense.average.count = average
        else:
            print("Cannot set average without a powermeter")

    def initUI(self):
        self.setWindowTitle(f"PowerMeter ({self.device})")
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
        if os.name == "nt":  # Windows PyQT6 will freeze up if we go too high?!
            self.samplerate.addItem("30 Hz", 20)
        else:
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
        self.startstop.setStyleSheet("color: red; font-weight: bold")

        def startstop():
            if not self.startstop.isChecked():
                self.timer.start()
                self.startstop.setStyleSheet("color: red; font-weight: bold")
                self.startstop.setText("STOP")
            else:
                self.timer.stop()
                self.startstop.setStyleSheet(
                    "background-color: red; color: white; font-weight: bold"
                )
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
        main = QGridLayout()
        main.setColumnStretch(0, 2)
        main.setColumnStretch(1, 1)
        main.setColumnStretch(2, 5)
        main.addWidget(QLabel("Wavelength:"), 0, 0)
        main.addWidget(self.wavelength, 0, 1)
        main.addWidget(QLabel("Sample rate:"), 1, 0)
        main.addWidget(self.samplerate, 1, 1)
        main.addWidget(QLabel("Averaging:"), 2, 0)
        main.addWidget(self.average, 2, 1)
        main.addWidget(self.current_power, 0, 2, 4, 1, Qt.AlignmentFlag.AlignCenter)
        main.addWidget(self.startstop, 3, 0)
        main.addWidget(self.reset, 3, 1)

        self.layout.addLayout(main)
        # plot of power
        self.maxline, self.mainplot, self.maincurve = self.create_mainplot()
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

        self.save = QPushButton("Save")

        def save(self):
            filename = f"PM100D_{time()}.csv"
            options = QFileDialog.Option.DontUseNativeDialog
            fileName, _ = QFileDialog.getSaveFileName(
                self,
                f"Save File",
                filename,
                "All Files(*);;Text Files(*.txt)",
                options=options,
            )
            if fileName:
                with open(fileName, "w") as f:
                    f.write("Time (s), Power (W)\n")
                    for t, p in zip(self.timeData, self.powerData):
                        f.write(f"{t}, {p}\n")
                self.fileName = fileName

        self.save.clicked.connect(lambda: save(self))
        self.save.setFlat(True)
        self.save.setStyleSheet("color: gray; font-weight: bold")

        self.numvals = QLabel("# readings: 0")
        self.numvals.setStyleSheet("QLabel { color : gray; }")

        statsHBox.addWidget(self.fps)
        statsHBox.addStretch()
        statsHBox.addWidget(self.save)
        statsHBox.addStretch()
        statsHBox.addWidget(self.numvals)
        self.layout.addLayout(statsHBox)

        self.show()


def forkPlot(device):
    app = pg.mkQApp(f"PowerMeter {device}")
    app.setWindowIcon(
        QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    app.setStyle("Fusion")

    power_meter = initPowermeter(device)

    window = PowerMeterPlot(powermeter=power_meter, device=device)
    window.show()
    window.setWindowIcon(
        QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )

    pg.exec()


def initPowermeter(device):
    if os.name == "nt":
        devices = PM100D.listDevices()
        power_meter = devices.connect(device)
        power_meter.setPowerAutoRange(True)
        power_meter.setWaveLength(780)
        return power_meter
    else:
        inst = USBTMC(device)
        power_meter = PM100D(inst=inst)
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

        self.setWindowTitle("PM100D")
        self.setGeometry(self.x(), self.y(), 250, 50)

        self.listWidget = QListWidget(self)
        self.shutdownButton = QPushButton("Shutdown", self)
        self.shutdownButton.setStyleSheet("color: red; font-weight: bold")
        self.shutdownButton.clicked.connect(self.shutdown_program)
        # automatically launch all powermeters
        self.autoButton = QPushButton("Auto")
        self.autoButton.setStyleSheet("color: green; font-weight: bold")

        def setauto():
            self.auto = not self.auto
            if not self.autoButton.isChecked():
                self.autoButton.setStyleSheet("color: green; font-weight: bold")
                self.autoButton.setText("Manual")
            else:
                self.autoButton.setStyleSheet(
                    "background-color: green; color: white; font-weight: bold"
                )
                self.autoButton.setText("Auto")

        self.autoButton.setCheckable(True)
        self.auto = False
        self.autoButton.setChecked(self.auto)
        self.autoButton.clicked.connect(setauto)

        layout = QVBoxLayout()
        layout.addWidget(self.listWidget)

        hbox = QHBoxLayout()
        # 1 : 3 ratio of auto to shutdown button
        hbox.addWidget(self.autoButton, 1)
        hbox.addWidget(self.shutdownButton, 3)
        layout.addLayout(hbox)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.main_loop)
        self.timer.start(100)
        self.main_loop()

    def shutdown_program(self):
        print("Shutting down program")
        for item in self.listWidget.findItems("*", Qt.MatchFlag.MatchWildcard):
            if item.data is not None:
                item.data.kill()
        QApplication.instance().quit()

    def main_loop(self):
        def add_device(dev):
            item = QListWidgetItem()
            item.setText(dev)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.data = None
            self.listWidget.addItem(item)

        # keep the active powermeters up to date with the selection in qlistwidget
        if os.name == "nt":
            list = PM100D.listDevices()
            ports = list.resourceName
            serials = list.serialNumber
            # can only manage those that aren't connected yet as the others are anonymous
            ports = [p for p, s in zip(ports, serials) if s != "n/a"]
        else:
            ports = glob.glob("/dev/usbtmc*")
        for dev in ports:
            # make sure all plugged in powermeters are listed
            items = self.listWidget.findItems(dev, Qt.MatchFlag.MatchExactly)
            if not items:
                add_device(dev)
                continue

            # if the powermeter is checked, start it
            item = items[0]
            if item.checkState() == Qt.CheckState.Checked:
                if item.data is None:  # someone just checked it
                    item.data = mp.Process(target=forkPlot, args=(dev,))
                    item.data.start()
                    now = time()
                    while not item.data.is_alive() and time() - now < 1:
                        sleep(0.05)
                elif not item.data.is_alive():  # someone killed the plot window
                    if self.auto:
                        item.data = mp.Process(target=forkPlot, args=(dev,))
                        item.data.start()
                        now = time()
                        while not item.data.is_alive() and time() - now < 1:
                            sleep(0.05)
                    else:
                        item.data.kill()
                        item.data = None
                        item.setCheckState(Qt.CheckState.Unchecked)
            elif item.data is not None:  # someone just unchecked it
                item.data.kill()
                item.data = None
            else:  # it's unchecked and not running
                if self.auto:  # force startup in auto mode
                    item.setCheckState(Qt.CheckState.Checked)

        # remove any powermeters that are not plugged in
        for i in range(self.listWidget.count()).__reversed__():
            if os.name == "nt":
                if not self.listWidget.item(i).text() in ports:
                    # if a process is running let it keep going
                    if (
                        self.listWidget.item(i).data is None
                        or not self.listWidget.item(i).data.is_alive()
                    ):
                        self.listWidget.takeItem(i)
            else:
                if not os.path.exists(self.listWidget.item(i).text()):
                    self.listWidget.takeItem(i)


if __name__ == "__main__":
    mp.set_start_method("spawn")

    # app = QApplication([])
    app = pg.mkQApp("PM100D")
    app.setWindowIcon(
        QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    app.setStyle("Fusion")

    window = PowerMeterTracker()
    window.show()
    app.exec()
