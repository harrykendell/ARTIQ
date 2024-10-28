from ThorlabsPM100 import ThorlabsPM100
from usbtmc import USBTMC

import sys, os
import numpy as np
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QSpinBox
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
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

    def update_plot(self, new_data, num_points=100):
        self.data = self.data[-num_points:]
        self.data.append(new_data)
        self.ax.clear()

        # set axis labels and title
        self.ax.set_xlabel('reading #')
        self.ax.set_ylabel('Power (mW)')
        self.ax.plot(self.data, 'r-')
        self.draw()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Power Meter GUI')
        self.setGeometry(100, 100, 800, 600)

        self.plot_canvas = PlotCanvas(self)

        self.mean_label = QLabel('Mean: 0', self)
        self.std_label = QLabel('Std Dev: 0', self)

        self.num_points = 10_000
        self.n_selector = QSpinBox(self)
        self.n_selector.setRange(1, 10_000)
        self.n_selector.setValue(self.num_points)
        # update nump_points when editing finished
        def update_num_points(num):
            self.num_points = num
        self.n_selector.editingFinished.connect(lambda: update_num_points(self.n_selector.value()))

        layout = QVBoxLayout()
        layout.addWidget(self.plot_canvas)
        layout.addWidget(self.mean_label)
        layout.addWidget(self.std_label)
        layout.addWidget(self.n_selector)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        # check if the path exists and if not retry with exponential backoff
        backoff = 1
        while not os.path.exists('/dev/usbtmc1'):
            print("Device not found, retrying in %d seconds..." % backoff)
            sleep(backoff)
            backoff *= 2
            if backoff > 60:
                print("Device not found, exiting...")
                sys.exit(1)
                
        inst = USBTMC('/dev/usbtmc1')
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
        self.setWindowTitle(f'Power Meter Readings ({self.power_meter.sense.correction.wavelength} nm)')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(100)  # Update every .1 seconds


    def update(self):
        new_value = self.power_meter.read*1e3
        self.plot_canvas.update_plot(new_value,self.n_selector.value())

        data = self.plot_canvas.data
        self.mean_label.setText(f'Mean: {np.mean(data)}')
        self.std_label.setText(f'Std Dev: {np.std(data)}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    # Set a nice icon
    app.setWindowIcon(
    QIcon("/usr/share/icons/elementary-xfce/apps/128/invest-applet.png")
    )
    app.setStyle("Fusion")
    app.setApplicationName("Power Meter")
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
