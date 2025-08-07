import functools
import warnings

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter
from lmfit import Model
from scipy.ndimage import gaussian_filter

from artiq.language.units import MHz

warnings.filterwarnings("ignore", message="Using UFloat objects with std_dev==0")


def gaussian_2D(x, y, A, x0, y0, sx, sy, theta=0, z0=0):
    """Takes a meshgrid of x, y and returns the gaussian computed across all values. See
    https://en.wikipedia.org/wiki/Gaussian_function#Two-dimensional_Gaussian_function
    """
    cos_sq = np.square(np.cos(theta))
    sin_sq = np.square(np.sin(theta))
    sin2th = np.sin(2 * theta)
    sx_sq = np.square(sx)
    sy_sq = np.square(sy)

    # General 2D Gaussian equation parameters
    a = cos_sq / (2 * sx_sq) + sin_sq / (2 * sy_sq)
    b = sin2th / (4 * sy_sq) - sin2th / (4 * sx_sq)
    c = sin_sq / (2 * sx_sq) + cos_sq / (2 * sy_sq)

    quadratic = (
        a * np.square(x - x0) + 2 * b * (x - x0) * (y - y0) + c * np.square(y - y0)
    )
    return A * np.exp(-quadratic) + z0


def ravel(func):
    """Decorator that ravels the return value of the decorated function."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return np.ravel(func(*args, **kwargs))

    return wrapper


class AbsImage:
    nm = 1e-9
    um = 1e-6
    threshold = 0.1  # multiple of maximum light to count as in the beam

    def __init__(
        self,
        data,
        ref,
        bg,
        wavelength=780.24602089 * nm,
        detuning=0 * MHz,
        linewidth=6.065 * MHz,
        pixel_size=6.45 * um,
        magnification=None,
        fit_downsample=5,
    ):
        """AbsImage class for processing absorption images.

        Args:
            data (np.ndarray): The atom/light image.
            ref (np.ndarray): The light image with no atoms.
            bg (np.ndarray): The background image with no light or atoms.
            wavelength (float): The wavelength of the imaging transition.
            detuning (float): The detuning from the imaging transition.
            linewidth (float): The linewidth of the imaging transition.
            pixel_size (float): The size of the pixels in the camera.
            magnification (float): The magnification of the imaging system.\
        """
        assert data.shape == ref.shape == bg.shape
        self.data_image = np.rot90(data)
        self.ref_image = np.rot90(ref)
        self.bg_image = np.rot90(bg)

        self.height = self.data_image.shape[0]
        self.width = self.data_image.shape[1]
        # numpy images are y, x
        self.xy = np.mgrid[0 : self.height, 0 : self.width]
        self.fit_downsample = fit_downsample

        self.wavelength = wavelength
        self.detuning = detuning
        self.linewidth = linewidth
        self.pixel_size = pixel_size

        if magnification is None:
            # NB for now 50mm lens at 150mm distance focuses to 75mm away
            # self.magnification = 75 / 150 = 0.5
            raise ValueError(
                "Please set magnification for the PCO camera\nNB: For nowa 50mm lens at"
                " 150mm focuses to 75mm away, so set to 0.5"
            )
        self.magnification = magnification

    def all_info(self):
        """Returns a string of a dict with all the information about the image."""
        return f"""
            "wavelength": {self.wavelength},
            "detuning": {self.detuning},
            "linewidth": {self.linewidth},
            "pixel_size": {self.pixel_size},
            "magnification": {self.magnification},
            "atom_number": {self.atom_number},
            "peak_pixel": {self.peak},
            "centroid_pixel": {self.centroid},
            "best_values_pixel": {self.best_values},
            "multiply_by_me_to_convert_pixel_to_SI": {self.physical_scale},
        """

    @functools.cached_property
    def physical_scale(self):
        """Pixel to real-space size in m."""
        scale = self.pixel_size * (1 / self.magnification)
        return scale

    @functools.cached_property
    def optical_density(self):
        smoothed_transmission = gaussian_filter(self.transmission, sigma=1)
        od = -np.log(smoothed_transmission, where=smoothed_transmission > 0)
        return od

    @functools.cached_property
    def transmission(self):
        """Returns the beam and dark-field compensated transmission image.
        Dark-field is subtracted from both the atom image and the beam image,
        and the atom image is divided by the beam image, giving the transmission t^2.
        The values should optimally lie in the range of [0, 1] but can realistically be
        in the range of [-0.1, 1.5] due to noise and beam variation across images."""

        atoms = np.subtract(self.data_image, self.bg_image)
        light = np.subtract(self.ref_image, self.bg_image)

        # If the light data is below some threshold, we assume that any
        # atom data at this location is invalid and treat as if no transmission.
        # The threshold value was selected experimentally
        threshold = np.max(atoms) * AbsImage.threshold
        transmission = np.divide(atoms, light, where=light > threshold)
        transmission[light <= threshold] = 1
        np.clip(transmission, a_min=0, a_max=1, out=transmission)

        return transmission

    @functools.cached_property
    def absorption(self):
        """Raw absorption data"""
        return 1 - self.transmission

    @functools.cached_property
    def atom_number(self):
        """Calculates the total atom number from the transmission ROI values."""
        # light and camera parameters
        sigma_0 = (3 / (2 * np.pi)) * np.square(self.wavelength)  # cross-section
        sigma = sigma_0 * np.reciprocal(
            1 + np.square(self.detuning / (self.linewidth / 2))
        )  # off resonance
        area = np.square(self.physical_scale)  # pixel area in SI units

        optical_density = self.optical_density[self.sigma_mask]

        if np.max(optical_density) < 0.1:
            # logging.warning("There don't seem to be any atoms in the image")
            return -np.inf

        return (
            (area / sigma) * np.sum(optical_density) / 0.866
        )  # Divide by 1.5-sigma area

    @functools.cached_property
    def peak(self):
        """Returns y, x, z of brightest pixel in absorption"""
        y, x = np.unravel_index(
            np.argmax(self.optical_density), self.optical_density.shape
        )
        z = self.optical_density[y, x]
        return y, x, z

    @functools.cached_property
    def centroid(self):
        """Returns y, x, z of the centroid of the absorption image"""
        y, x = self.xy
        A = np.sum(self.optical_density)
        y_c = int(np.sum(y * self.optical_density) / A)
        x_c = int(np.sum(x * self.optical_density) / A)
        z_c = self.optical_density[y_c, x_c]
        return y_c, x_c, z_c

    @functools.cached_property
    def sigma_mask(self):
        """Returns a numpy mask of pixels within the
        2-sigma limit of the model (no ROI)"""
        bp_2D = self.best_values
        y0, x0, a, b, theta = (bp_2D[k] for k in ("y0", "x0", "sy", "sx", "theta"))
        y, x = np.ogrid[0 : self.height, 0 : self.width]

        # https://math.stackexchange.com/a/434482
        maj_axis = np.square((x - x0) * np.cos(theta) - (y - y0) * np.sin(theta))
        min_axis = np.square((x - x0) * np.sin(theta) + (y - y0) * np.cos(theta))
        bound = 4.343  # chi2.ppf(0.886, df=2)

        array = np.zeros(self.data_image.shape, dtype="bool")
        array[maj_axis / np.square(b) + min_axis / np.square(a) <= bound] = True
        return array

    @functools.cached_property
    def fit(self):
        """Fits a 2D Gaussian against the absorption."""
        # logging.info("Running 2D fit...")

        y_mg, x_mg = self.xy
        model = Model(ravel(gaussian_2D), independent_vars=["x", "y"])

        y_c, x_c, A = self.centroid
        model.set_param_hint("A", value=A, min=0, max=6)
        model.set_param_hint(
            "x0", value=x_c, min=-0.1 * self.width, max=1.1 * self.width
        )
        model.set_param_hint(
            "y0", value=y_c, min=-0.1 * self.width, max=1.1 * self.height
        )

        model.set_param_hint("sx", value=self.width / 4, min=1, max=self.width)
        model.set_param_hint("sy", value=self.height / 4, min=1, max=self.height)
        model.set_param_hint(
            "theta", value=0, min=-np.pi / 2, max=np.pi / 2, vary=False
        )
        model.set_param_hint("z0", value=0, vary=False)

        result = model.fit(
            np.ravel(self.optical_density[:: self.fit_downsample]),
            x=x_mg[:: self.fit_downsample],
            y=y_mg[:: self.fit_downsample],
            max_nfev=1000,
            fit_kws={"xtol": 1e-7},
        )

        return result

    @functools.cached_property
    def best_values(self):
        return self.fit.best_values

    @property
    def best_fit(self):
        """Returns the evaluated best fit.

        The fit has been reshaped to the original image size.
        """
        return self.eval(x=self.xy[1], y=self.xy[0]).reshape(self.height, self.width)

    def eval(self, *, x, y):
        """Evaluates the fit at the given coordinates."""
        return self.fit.eval(x=x, y=y)

    @staticmethod
    def fake(num_gaussians=1):
        """
        Creates a randomised fake AbsImage object for testing purposes.
        """
        height, width = 1392, 1040
        posy = np.random.uniform(width / 3, width * 2 / 3)
        posx = np.random.uniform(height / 3, height * 2 / 3)

        x, y = np.mgrid[0:height, 0:width]
        fake_ref = gaussian_2D(
            x,
            y,
            A=np.random.uniform(10000, 16000),
            x0=posx,
            y0=posy,
            sx=np.random.uniform(width / 4, width / 2),
            sy=np.random.uniform(height / 4, height / 2),
            theta=np.random.uniform(0, np.pi),
        )

        sx = np.random.uniform(width / 20, width / 5)
        sy = np.random.uniform(height / 20, height / 5)
        atom_cloud = fake_ref * 0
        for num in range(1, num_gaussians + 1):
            atom_cloud += gaussian_2D(
                x,
                y,
                A=np.random.uniform(-1, -0.0) / num_gaussians,
                x0=posx * np.random.uniform(0.7, 1.3 / num**0.5),
                y0=posy * np.random.uniform(0.7, 1.3 / num**0.5),
                sx=sx * np.random.uniform(0.5, 1.5 / num**0.5),
                sy=sy * np.random.uniform(0.5, 1.5 / num**0.5),
                theta=np.random.uniform(0, np.pi),
                z0=1 / num_gaussians,
            )

        fake_data = gaussian_filter(np.multiply(fake_ref, atom_cloud), width // 20)

        # add some noise
        noise = 0
        fake_ref += np.random.normal(0, noise, size=fake_ref.shape)
        fake_data += np.random.normal(0, noise, size=fake_data.shape)
        fake_bg = np.random.normal(0, noise, size=fake_ref.shape)

        return AbsImage(
            data=fake_data,
            ref=fake_ref,
            bg=fake_bg,
            magnification=0.5,
        )

    def plot(self, fig=None):
        """
        Plots raw images, optical density, best fit, and fit stats using a compact layout.
        """
        if fig is None:
            fig = plt.figure(figsize=(8, 8))

        # Clear the figure to start fresh
        fig.clf()

        # Common GridSpec parameters
        grid_params = {
            "figure": fig,
            "width_ratios": [1, 1, 1, 0.2],
            "left": 0.1,
            "right": 0.85,
            "wspace": 0.05,
        }

        # Create top and bottom grids with specific vertical spacing
        gs_top = GridSpec(1, 4, top=0.95, bottom=0.75, **grid_params)  # For raw images
        gs_bottom = GridSpec(1, 4, top=0.68, bottom=0.12, **grid_params)  # For OD plot

        # Create all axes in a more compact way
        raw_axes = [fig.add_subplot(gs_top[0, i]) for i in range(3)]
        cax_raw = fig.add_subplot(gs_top[0, 3])
        od_ax = fig.add_subplot(gs_bottom[0, 0:3])
        cax_od = fig.add_subplot(gs_bottom[0, 3])

        # Group all content axes for setting properties
        axes = raw_axes + [od_ax]
        for ax in axes:
            ax.set_facecolor("none")

        # Prepare data
        raw_images = [self.data_image, self.ref_image, self.bg_image]
        input_min, input_max = (
            min(np.min(img) for img in raw_images),
            max(np.max(img) for img in raw_images),
        )

        def plot_image(ax, img, title):
            """Helper function to plot images with common settings."""
            im = ax.imshow(
                img,
                cmap="gray",
                vmin=input_min,
                vmax=input_max,
                origin="lower",
                aspect="equal",
            )
            ax.set(xticks=[], yticks=[], xlabel="", ylabel="")
            ax.set_title(title, fontweight="bold", pad=2)
            return im

        # Plot raw images
        for ax, img, title in zip(
            raw_axes, raw_images, ["Atoms", "Reference", "Background"]
        ):
            im = plot_image(ax, img, title)
        cb_raw = fig.colorbar(
            im,
            cax=cax_raw,
            orientation="vertical",
            label="Electron Count",
        )
        cb_raw.ax.tick_params(labelsize=8)
        cb_raw.ax.yaxis.set_label_coords(3, 0.5)
        e_count_below_max = [v * 1e3 for v in range(0, 16, 5) if v * 1.2e3 <= input_max]
        cb_raw.set_ticks(sorted(set(e_count_below_max + [input_max])))

        # Get tick labels and make the input_max label red if it saturated
        tick_labels = cb_raw.ax.get_yticklabels()
        for label in tick_labels:
            if float(label.get_text()) > 15999:  # 16k is the saturation point
                label.set_color("red")
                label.set_fontweight("bold")
        cb_raw.ax.set_yticklabels(tick_labels)

        # Real-space extent
        scale_mm = self.physical_scale * 1e3
        extent = [0, self.width * scale_mm, 0, self.height * scale_mm]
        formatter = FuncFormatter(lambda x, pos: f"{x:.1f}")

        # Plot parameters
        vmin, vmax = (
            min(np.min(self.optical_density), np.min(self.best_fit)),
            max(np.max(self.optical_density), np.max(self.best_fit)),
        )
        plot_params = {
            "cmap": "gray",
            "origin": "lower",
            "extent": extent,
            "vmin": vmin,
            "vmax": vmax,
            "aspect": "equal",
        }

        centroid_mm = (self.centroid[1] * scale_mm, self.centroid[0] * scale_mm)
        peak_mm = (self.peak[1] * scale_mm, self.peak[0] * scale_mm)
        fit_center_mm = (
            self.best_values["x0"] * scale_mm,
            self.best_values["y0"] * scale_mm,
        )
        x_contour, y_contour = (
            np.linspace(extent[0], extent[1], self.width),
            np.linspace(extent[2], extent[3], self.height),
        )

        # OD plot
        im1 = od_ax.imshow(self.optical_density, **plot_params)
        od_ax.set(xlabel="Horizontal position (mm)", ylabel="Vertical position (mm)")
        od_ax.xaxis.labelpad = 2
        od_ax.yaxis.labelpad = 2
        od_ax.tick_params(axis="both", which="major", labelsize=8)

        od_ax.set_title(
            "Optical Density",
            fontweight="bold",
            pad=2,
        )
        od_ax.contour(
            x_contour,
            y_contour,
            self.sigma_mask,
            colors="red",
            linewidths=1,
        )

        # show the fitted slices
        od_ax.plot(
            x_contour,
            self.best_fit[self.peak[0], :],
            color="green",
            linewidth=2,
            label="Horizontal fit",
        )
        od_ax.plot(
            self.best_fit[:, self.peak[1]],
            y_contour,
            color="green",
            linewidth=2,
            label="Vertical fit",
        )
        # show the od slices too
        od_ax.plot(
            x_contour,
            self.optical_density[self.peak[0], :],
            color="white",
            linewidth=2,
            label="Horizontal OD",
        )
        od_ax.plot(
            self.optical_density[:, self.peak[1]],
            y_contour,
            color="white",
            linewidth=2,
            label="Vertical OD",
        )

        # show the 1stdev fitted gaussian outline - contour of A/e
        od_ax.contour(
            x_contour,
            y_contour,
            self.best_fit,
            levels=[self.fit.best_values["A"] * np.exp(-1)],
            colors="green",
            linewidths=1,
        )
        od_ax.scatter(*fit_center_mm, color="green", s=25)
        od_ax.scatter(*centroid_mm, color="orange", s=25)
        od_ax.scatter(*peak_mm, color="blue", s=25)
        od_ax.xaxis.set_major_formatter(formatter)
        od_ax.yaxis.set_major_formatter(formatter)
        od_ax.set_xlim(extent[0], extent[1])
        od_ax.set_ylim(extent[2], extent[3])

        from matplotlib.lines import Line2D

        legend_elements = [
            Line2D([0], [0], color="red", lw=1, label="2σ Atom mask")
        ] + [
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                markerfacecolor=color,
                markersize=5,
                label=label,
            )
            for color, label in [
                ("green", "Fitted Gaussian"),
                ("orange", "Centroid"),
                ("blue", "Peak"),
            ]
        ]

        od_ax.legend(
            handles=legend_elements,
            loc="upper right",
            fontsize=8,
            handlelength=1.2,
            handletextpad=0.5,
        )

        cb_od = fig.colorbar(
            im1,
            cax=cax_od,
            orientation="vertical",
            label="Optical Density",
        )
        cb_od.ax.tick_params(labelsize=8)
        cb_od.ax.yaxis.set_label_coords(3, 0.5)

        # For Qt integration, draw once to calculate sizes
        fig.canvas.draw_idle()

        return fig, axes + [cax_raw, cax_od]
