#!/usr/bin/env python3

import PyQt5  # make sure pyqtgraph imports Qt5
from PyQt5 import QtWidgets, QtCore

import matplotlib

matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from artiq.applets.simple import TitleApplet
from repository.imaging.processor import AbsImage


class MatplotlibCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=8, height=6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)
        super(MatplotlibCanvas, self).__init__(self.fig)
        self.axes = None


class AbsorptionView(QtWidgets.QWidget):
    def __init__(self, args, req):
        QtWidgets.QWidget.__init__(self)
        self.args = args
        self.req = req
        self.absimg = None

        #set size
        self.setMinimumSize(800, 600)

        # Create the main layout
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Create the matplotlib canvas
        self.canvas = MatplotlibCanvas(self, width=9, height=6)
        layout.addWidget(self.canvas)

        # Add status label at the bottom
        self.status_label = QtWidgets.QLabel("Waiting for data...")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 10pt;")
        layout.addWidget(self.status_label)

    def data_changed(self, value, metadata, persist, mods, title=None):
        # Update title if provided
        if title is not None:
            self.setWindowTitle(title)

        # Get data from the datasets
        try:
            # Check if all required datasets are available
            if all(
                value.get(getattr(self.args, key)) is not None
                for key in ["TOF", "REF", "BG"]
            ):
                # Get the image data
                tof_data = value[self.args.TOF]
                ref_data = value[self.args.REF]
                bg_data = value[self.args.BG]

                # Create AbsImage object
                self.absimg = AbsImage(
                    data=tof_data,
                    ref=ref_data,
                    bg=bg_data,
                    magnification=0.5,  # Set default magnification
                )

                # Clear previous plot
                self.canvas.fig.clear()

                try:
                    # Use the AbsImage plot method to generate the visualization
                    fig, axes = self.absimg.plot(fig=self.canvas.fig)

                    # Store the axes for potential future reference
                    self.canvas.axes = axes

                    # Update the canvas
                    self.canvas.draw()

                    # Update status
                    atom_number = self.absimg.atom_number
                    r_squared = self.absimg.fit.summary()["rsquared"]
                    self.status_label.setText(
                        f"Atom Number: {atom_number:.2e}, R²: {r_squared:.3f}"
                    )

                except Exception as plot_error:
                    self.status_label.setText(f"Error in plot: {str(plot_error)}")
                    raise

        except Exception as e:
            import traceback

            self.status_label.setText(f"Error: {str(e)}")
            print(f"Error updating data: {e}")
            traceback.print_exc()


def main():
    applet = TitleApplet(AbsorptionView)
    # Hardcoded dataset paths as required
    applet._arggroup_datasets.add_argument(
        "--TOF", default="Images.absorption.TOF", help="Data Image"
    )
    applet.dataset_args.add("TOF")

    applet._arggroup_datasets.add_argument(
        "--REF", default="Images.absorption.REF", help="Reference Image"
    )
    applet.dataset_args.add("REF")

    applet._arggroup_datasets.add_argument(
        "--BG", default="Images.absorption.BG", help="Background Image"
    )
    applet.dataset_args.add("BG")

    applet.run()


if __name__ == "__main__":
    main()
