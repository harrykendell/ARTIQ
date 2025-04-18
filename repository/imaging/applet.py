#!/usr/bin/env python3

import PyQt5  # noqa: F401 # make sure pyqtgraph imports Qt5
from PyQt5 import QtWidgets, QtCore

import matplotlib

matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from artiq.applets.simple import TitleApplet  # noqa: E402
from repository.imaging.processor import AbsImage  # noqa: E402


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
        self.expansion_time = None

        # Create the main layout
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Create the matplotlib canvas
        self.canvas = MatplotlibCanvas(self, width=8, height=8)
        layout.addWidget(self.canvas)

        # Add status label at the bottom
        self.status_label = QtWidgets.QLabel("Waiting for data...")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 10pt;")
        self.status_label.setWordWrap(True)

        # Add save button
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.setEnabled(False)  # Disable until data is available
        self.save_button.clicked.connect(self.save_data)

        # Add button and label to layout
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addStretch()

        layout.addWidget(self.status_label)
        layout.addLayout(button_layout)

    def save_data(self):
        """Save the images and fit results to a local directory"""
        try:
            import os
            import numpy as np
            from datetime import datetime

            # Create timestamp for unique filenames
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Create a 'saved_images' directory in the current working directory
            save_dir = os.path.join(os.getcwd(), "absorption_images", timestamp)
            os.makedirs(save_dir, exist_ok=True)

            # Save the raw images
            np.save(
                os.path.join(save_dir, f"{timestamp}_tof.npy"), self.absimg.data_image
            )
            np.save(
                os.path.join(save_dir, f"{timestamp}_ref.npy"), self.absimg.ref_image
            )
            np.save(os.path.join(save_dir, f"{timestamp}_bg.npy"), self.absimg.bg_image)

            # Save the optical density
            np.save(
                os.path.join(save_dir, f"{timestamp}_od.npy"),
                self.absimg.optical_density,
            )

            # Save the visualization
            fig_path = os.path.join(save_dir, f"{timestamp}_plot.png")
            self.canvas.fig.savefig(fig_path, dpi=300, bbox_inches="tight")

            # Save fit parameters as text file
            fit_path = os.path.join(save_dir, f"{timestamp}_fit_results.txt")
            with open(fit_path, "w") as f:
                f.write(f"Atom number: {self.absimg.atom_number:.4e}\n")
                f.write(f"R-squared: {self.absimg.fit.summary()['rsquared']:.4f}\n")
                f.write("Fit results (pixel units):\n")
                for param_name, param_value in self.absimg.fit.best_values.items():
                    f.write(f"\t{param_name}: {param_value:.6f}\n")
                f.write(f"Expansion time: {self.expansion_time} ms\n")
                f.write(f"Wavelength: {self.absimg.wavelength} nm\n")
                f.write(f"Detuning: {self.absimg.detuning} MHz\n")
                f.write(f"Linewidth: {self.absimg.linewidth} MHz\n")
                f.write(f"Pixel size: {self.absimg.pixel_size} mm\n")
                f.write(f"Magnification: {self.absimg.magnification}\n")

            # set button to 'Saved'
            self.save_button.setText("Saved!")
            self.save_button.setEnabled(False)  # Disable until data is available

        except Exception as e:
            import traceback

            self.status_label.setText(f"Error saving data: {str(e)}")
            print(f"Error saving data: {e}")
            traceback.print_exc()

    def data_changed(self, value, metadata, persist, mods, title=None):
        # Update title if provided
        if title is not None:
            self.setWindowTitle(title)

        # Get data from the datasets
        try:
            # Check if all required datasets are available
            if all(
                value.get(getattr(self.args, key)) is not None
                for key in ["TOF", "REF", "BG", "expansion_time"]
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

                # Enable save button now that we have data
                self.save_button.setEnabled(True)
                self.save_button.setText("Save")

                # Clear previous plot
                self.canvas.fig.clear()

                try:
                    # Use the AbsImage plot method to generate the visualization
                    fig, axes = self.absimg.plot(fig=self.canvas.fig)

                    # Store the axes for potential future reference
                    self.canvas.axes = axes

                    # Update the canvas
                    self.canvas.draw()

                    # Add save button if it doesn't exist
                    if not hasattr(self, "save_button"):
                        self.save_button = QtWidgets.QPushButton("Save Images and Fit")
                        self.layout().addWidget(self.save_button)
                        self.save_button.clicked.connect(self.save_data)

                    # Enable the button
                    self.save_button.setEnabled(True)

                    # Update status - atom number, r-squared, sigma_x, sigma_y,
                    # expansion time
                    atom_number = self.absimg.atom_number
                    r_squared = self.absimg.fit.summary()["rsquared"]
                    self.expansion_time = (
                        value[self.args.expansion_time] * 1e3
                    )  # Convert to ms
                    sigmax = (
                        self.absimg.fit.best_values["sx"]
                        * self.absimg.physical_scale
                        * 1e3
                    )
                    sigmay = (
                        self.absimg.fit.best_values["sy"]
                        * self.absimg.physical_scale
                        * 1e3
                    )
                    self.status_label.setText(
                        f"""<div style="text-align:center; margin:0; padding:0">
                          <span style="font-weight:bold">Atom number:</span>\
                            {atom_number:.2e} &nbsp;
                          <span style="font-weight:bold">Expansion time:</span>\
                            {self.expansion_time:.2f} ms &nbsp;
                          <span style="font-weight:bold">Sigma:</span>\
                            ({sigmax:.2f}, {sigmay:.2f}) mm<br>
                          <span style="color:#CCC"><b>R-squared:</b>\
                          {r_squared:.2f}</span>
                        </div>"""
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

    applet._arggroup_datasets.add_argument(
        "--expansion_time",
        default="Images.absorption.expansion_time",
        help="Expansion time",
    )
    applet.dataset_args.add("expansion_time")

    applet.run()


if __name__ == "__main__":
    main()
