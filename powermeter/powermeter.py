from ThorlabsPM100 import ThorlabsPM100
from usbtmc import USBTMC

import argparse

import sys, os
import numpy as np
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QSpinBox
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
import pyqtgraph as pg

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from time import sleep

class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None):
        fig = Figure()
        self.ax = fig.subplots()
        super().__init__(fig)
        self.setParent(parent)
        self.data = []
        self.xs = []

    def update_plot(self, new_data, start=0,end=100):
        self.data.append(new_data)
        self.xs.append(len(self.data))
        self.ax.clear()

        start = max(0, start)
        end = min(len(self.data), end)

        # set axis labels and title
        self.ax.set_xlabel('reading #')
        self.ax.set_ylabel('Power (mW)')
        # make sure we have enough points
        self.ax.plot(self.xs[start:end],self.data[start:end], 'r-')
        self.draw()

class MainWindow(QMainWindow):
    def __init__(self, device):
        super().__init__()
        self.setWindowTitle(f'Power Meter GUI ({device})')
        self.setGeometry(100, 100, 800, 600)

        self.plot_canvas = PlotCanvas(self)

        self.mean_label = QLabel('Mean: 0', self)
        self.std_label = QLabel('Std Dev: 0', self)

        maxval = 1_000_000
        self.start_selector = QSpinBox(self)
        self.end_selector = QSpinBox(self)
        self.start_selector.setMaximum(maxval)
        self.start_selector.setValue(0)
        self.end_selector.setMaximum(maxval)
        self.end_selector.setValue(maxval)

        layout = QVBoxLayout()
        layout.addWidget(self.plot_canvas)
        layout.addWidget(self.mean_label)
        layout.addWidget(self.std_label)

        rangebox = QHBoxLayout()
        rangebox.addWidget(QLabel("Start:"))
        rangebox.addWidget(self.start_selector)
        rangebox.addWidget(QLabel("End:"))
        rangebox.addWidget(self.end_selector)
        layout.addLayout(rangebox)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
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
        self.power_meter = ThorlabsPM100(inst = inst)
        self.power_meter.system.beeper.immediate()

        print("Measurement type :", self.power_meter.getconfigure)
        print("Current value    :", self.power_meter.read)
        print("Wavelength       :", self.power_meter.sense.correction.wavelength)

        print("Power range limit:", self.power_meter.sense.power.dc.range.upper)

        print("Set range auto and wait 500ms    ...")
        sleep(.5)
        self.power_meter.sense.power.dc.range.auto = "ON"
        print("Set bandwidth to High")
        self.power_meter.input.pdiode.filter.lpass.state = 0

        self.power_meter.sense.average.count = 10

        # set windows title
        self.setWindowTitle(f'Power Meter Readings ({device} @ {self.power_meter.sense.correction.wavelength} nm)')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(100)  # Update every .1 seconds

    def update(self):
        new_value = self.power_meter.read*1e3
        self.plot_canvas.update_plot(new_value,self.start_selector.value(),self.end_selector.value())

        data = self.plot_canvas.data
        self.mean_label.setText(f'Mean: {np.mean(data)}')
        self.std_label.setText(f'Std Dev: {np.std(data)}')

def launchWindow(device):
    app = QApplication(sys.argv)
    # Set a nice icon
    app.setWindowIcon(
    QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    app.setStyle("Fusion")
    app.setApplicationName("Power Meter")

    window = MainWindow(device)
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    # parse command line arguments for the device path
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", help="Display all devices", action="store_true")
    parser.add_argument("--device", help="USB device path", default="/dev/usbtmc1")
    args = parser.parse_args()

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
                    processes[device] = Process(target=launchWindow, args=(f"/dev/{device}",))
                    processes[device].start()

            sleep(1)
    else:
        print(f"Starting process for {args.device}")
        launchWindow(args.device)