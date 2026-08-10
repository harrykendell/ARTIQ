import dataclasses
import functools
import math
import warnings
import numpy as np
import scipy.constants as const
import matplotlib.pyplot as plt
from lmfit import Model
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter
from scipy.ndimage import gaussian_filter, label
from dataclasses import dataclass
from artiq.language.units import MHz

warnings.filterwarnings("ignore", message="Using UFloat objects with std_dev==0")


# https://core.ac.uk/download/pdf/82969205.pdf, link to the reference absorption imaging


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


@dataclass(frozen=True)
class AbsImageSettings:
    wavelength: float = 780.24602089 * 1e-9  # m
    detuning: float = 0 * MHz
    linewidth: float = 6.065 * MHz
    atom_mass: float = 1.443e-25  # kg, mass of Rb87
    pixel_size: float = 6.45e-6  # m
    fit_downsample: int = 5
    magnification: float = 0.227  # Set to None to force user to specify
    time_of_flight: float = 0.0  # s; retained in serialized image settings

    # PSD estimation parameters
    temperature: float = 26.54e-6  # K

    # Image processing and fit controls. Defaults reproduce the regression-tested
    # beam-aware fit while remaining compatible with older serialized settings.
    beam_threshold: float = 0.05
    image_smoothing_sigma: float = 1.0

    # need this to be pyon serializable for dataset storage
    def to_dataset(self):
        return str(str(dataclasses.asdict(self)))

    @staticmethod
    def from_dataset(d: str):
        return AbsImageSettings(**eval(d))


class AbsImage:
    analysis_schema = "absorption-image-analysis/v1"
    nm = 1e-9
    um = 1e-6

    def __init__(
        self,
        data,
        ref,
        bg,
        settings: AbsImageSettings = AbsImageSettings(),
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
        self.data_image = np.asarray(np.rot90(data), dtype=np.float64)
        self.ref_image = np.asarray(np.rot90(ref), dtype=np.float64)
        self.bg_image = np.asarray(np.rot90(bg), dtype=np.float64)

        self.height = self.data_image.shape[0]
        self.width = self.data_image.shape[1]
        # numpy images are y, x
        self.xy = np.mgrid[0 : self.height, 0 : self.width]
        self.settings = settings

        if self.settings.magnification is None:
            # NB for now 50mm lens at 150mm distance focuses to 75mm away
            # self.magnification = 75 / 150 = 0.5
            raise ValueError(
                "Please set magnification for the PCO camera\nNB: For nowa 50mm lens at"
                " 150mm focuses to 75mm away, so set to 0.5"
            )
        self.magnification = self.settings.magnification

    def all_info(self):
        """Returns a string of a dict with all the information about the image."""
        return f"""
            "wavelength": {self.settings.wavelength},
            "detuning": {self.settings.detuning},
            "linewidth": {self.settings.linewidth},
            "pixel_size": {self.settings.pixel_size},
            "magnification": {self.magnification},
            "atom_number": {self.atom_number},
            "peak_pixel": {self.peak},
            "centroid_pixel": {self.centroid},
            "best_values_pixel": {self.best_values},
            "multiply_by_me_to_convert_pixel_to_SI": {self.physical_scale},
            "physical_scale": {self.physical_scale},
            "phase_space_density": {self.phase_space_density},
            "peak_optical_density": {self.peak[2]},
            "Peak density (atoms/cm^3)": {self.phase_space_density[0] * 1e-6:.2e},
            "sigmax": {self.best_values["sx"]},
            "sigmay": {self.best_values["sy"]},
            "time_of_flight": {self.settings.time_of_flight},
            "sigmax_mm": {self.best_values["sx"] * self.physical_scale * 1e3},
            "sigmay_mm": {self.best_values["sy"] * self.physical_scale * 1e3},
        """

    def analysis_payload(self, *, frame_timestamp):
        """Return the fitted image analysis as a primitive dataset payload.

        ``Images.absorption.timestamp`` remains the frame-complete signal.  The
        matching timestamp in this payload lets other consumers reuse this fit
        without accidentally pairing it with an older set of camera frames.
        """

        def finite_number(value):
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if math.isfinite(number) else None

        def point(value):
            try:
                return [finite_number(item) for item in value[:3]]
            except (TypeError, IndexError):
                return None

        fit = self.fit
        best_values = {
            name: finite_number(self.best_values.get(name))
            for name in ("A", "x0", "y0", "sx", "sy", "theta", "z0")
        }
        fit_details = {
            "model": "gaussian_2D",
            "best_values": best_values,
            "success": bool(getattr(fit, "success", False)),
            "message": str(getattr(fit, "message", "")),
        }
        fit_details["rsquared"] = finite_number(getattr(fit, "rsquared", None))

        peak_density, wavelength, density = self.phase_space_density
        return {
            "schema": self.analysis_schema,
            "processor": "repository.imaging.processor.AbsImage",
            "frame_timestamp": finite_number(frame_timestamp),
            "source_shape": [int(self.height), int(self.width)],
            "fit": fit_details,
            "atom_number": finite_number(self.atom_number),
            "centroid_px": point(self.centroid),
            "peak_px": point(self.peak),
            "phase_space_density": {
                "peak_density_atoms_per_m3": finite_number(peak_density),
                "thermal_de_broglie_wavelength_m": finite_number(wavelength),
                "phase_space_density": finite_number(density),
            },
            "physical_scale_m_per_px": finite_number(self.physical_scale),
        }

    @functools.cached_property
    def physical_scale(self):
        """Pixel to real-space size in m."""
        scale = self.settings.pixel_size * (1 / self.settings.magnification)
        return scale

    @staticmethod
    def _largest_component(mask):
        """Return the largest connected True component in a boolean mask."""
        labelled, count = label(mask)
        if count == 0:
            return mask
        sizes = np.bincount(labelled.ravel())
        sizes[0] = 0
        return labelled == int(np.argmax(sizes))

    @staticmethod
    def _robust_location_scale(values):
        """Return median and a MAD-based robust standard deviation."""
        values = np.asarray(values)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return 0.0, 1.0
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        return median, max(1.4826 * mad, 1e-6)

    @functools.cached_property
    def smoothed_atoms(self):
        """Dark-subtracted atom frame used to form transmission."""
        return gaussian_filter(
            np.subtract(self.data_image, self.bg_image),
            sigma=self.settings.image_smoothing_sigma,
        )

    @functools.cached_property
    def smoothed_light(self):
        """Dark-subtracted reference frame used to form transmission."""
        return gaussian_filter(
            np.subtract(self.ref_image, self.bg_image),
            sigma=self.settings.image_smoothing_sigma,
        )

    @functools.cached_property
    def beam_mask(self):
        """Pixels reliably illuminated by the absorption-imaging beam.

        The reference image, rather than the atom image, defines where the
        transmission denominator is trustworthy. The largest connected beam is
        retained.
        """
        light = self.smoothed_light
        finite_light = light[np.isfinite(light)]
        if finite_light.size == 0:
            return np.ones_like(light, dtype=bool)

        light_peak = float(np.nanpercentile(finite_light, 99.9))
        if not np.isfinite(light_peak) or light_peak <= 0:
            mask = np.isfinite(light) & (light > 0)
        else:
            mask = np.isfinite(light) & (
                light > self.settings.beam_threshold * light_peak
            )

        mask = self._largest_component(mask)
        if not np.any(mask):
            return np.isfinite(light)

        return mask

    @functools.cached_property
    def transmission(self):
        """Beam- and dark-field-compensated transmission.

        The lower bound is clipped to keep the logarithm finite. Pixels outside ``beam_mask`` are set to one.
        """
        transmission = np.ones_like(self.smoothed_atoms, dtype=np.float64)
        valid = self.beam_mask & np.isfinite(self.smoothed_light)
        valid &= self.smoothed_light > 0

        np.divide(
            self.smoothed_atoms,
            self.smoothed_light,
            out=transmission,
            where=valid,
        )
        transmission[valid] = np.maximum(transmission[valid], 1e-4)
        transmission[~valid] = 1.0
        return transmission

    @functools.cached_property
    def optical_density(self):
        """Signed optical density used for fitting.

        Negative values are retained inside the illuminated beam. This avoids
        rectifying camera and reference-frame noise into a positive OD pedestal.
        """
        od = np.zeros_like(self.transmission, dtype=np.float64)
        od[self.beam_mask] = -np.log(self.transmission[self.beam_mask])
        return od

    @functools.cached_property
    def cloud_optical_density(self):
        """Positive atom-cloud OD after removal of the fitted background offset."""
        cloud_od = np.zeros_like(self.optical_density, dtype=np.float64)
        z0 = float(self.best_values.get("z0", 0.0))
        cloud_od[self.beam_mask] = np.clip(
            self.optical_density[self.beam_mask] - z0,
            0,
            None,
        )
        return cloud_od

    @functools.cached_property
    def sigmax(self):
        """Returns the fitted sigma_x in pixels."""
        return self.best_values["sx"]

    @functools.cached_property
    def sigmay(self):
        """Returns the fitted sigma_y in pixels."""
        return self.best_values["sy"]

    @functools.cached_property
    def absorption(self):
        """Raw absorption data"""
        return 1 - self.transmission

    @functools.cached_property
    def atom_number(self):
        """Calculate atom number from background-corrected cloud OD."""
        sigma_0 = (3 / (2 * np.pi)) * np.square(self.settings.wavelength)
        sigma = sigma_0 * np.reciprocal(
            1
            + np.square(4 * np.square(self.settings.detuning / self.settings.linewidth))
        )
        area = np.square(self.physical_scale)  # pixel area in SI units

        integration_mask = self.sigma_mask & self.beam_mask
        optical_density = self.cloud_optical_density[integration_mask]

        if optical_density.size == 0 or np.max(optical_density) < 0.1:
            return -np.inf

        # Divided by 1.5-sigma area for a 2D Gaussian to get the total number of atoms
        return (area / sigma) * np.sum(optical_density) / 0.866

    @functools.cached_property
    def peak(self):
        """Return y, x, and peak background-corrected cloud OD in pixels."""
        y, x = np.unravel_index(
            np.argmax(self.cloud_optical_density),
            self.cloud_optical_density.shape,
        )
        return y, x, self.cloud_optical_density[y, x]

    @functools.cached_property
    def centroid(self):
        """Return y, x, and OD at the cloud's positive-OD centroid in pixels."""
        y, x = self.xy
        weights = self.cloud_optical_density
        total = float(np.sum(weights))
        if not np.isfinite(total) or total <= 0:
            y_c = int(np.clip(round(self.best_values["y0"]), 0, self.height - 1))
            x_c = int(np.clip(round(self.best_values["x0"]), 0, self.width - 1))
        else:
            y_c = int(np.clip(round(np.sum(y * weights) / total), 0, self.height - 1))
            x_c = int(np.clip(round(np.sum(x * weights) / total), 0, self.width - 1))
        return y_c, x_c, weights[y_c, x_c]

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
        return array & self.beam_mask

    @functools.cached_property
    def x0(self):
        """Returns the x0 of the fitted gaussian in pixels."""
        return self.best_values["x0"]

    @functools.cached_property
    def y0(self):
        """Returns the y0 of the fitted gaussian in pixels."""
        return self.best_values["y0"]

    @functools.cached_property
    def _fit_initial_values(self):
        """Estimate cloud geometry without assuming a zero OD background."""
        od = self.optical_density
        mask = self.beam_mask & np.isfinite(od)
        y, x = self.xy

        values = od[mask]
        if values.size == 0:
            return {
                "A": 0.01,
                "x0": self.width / 2,
                "y0": self.height / 2,
                "sx": max(self.width / 8, 1),
                "sy": max(self.height / 8, 1),
                "z0": 0.0,
            }

        z0 = float(np.nanpercentile(values, 20))
        initial_image = np.zeros_like(od, dtype=np.float64)
        initial_image[mask] = np.clip(od[mask] - z0, 0, None)
        initial_image = gaussian_filter(initial_image, sigma=1)

        lower_half = values[values <= np.nanmedian(values)]
        _, noise = self._robust_location_scale(lower_half)
        peak = float(np.nanmax(initial_image[mask]))
        threshold = max(self.settings.beam_threshold * peak, 3.0 * noise)
        candidate = mask & (initial_image >= threshold)

        # Prefer the connected feature containing the strongest absorption.
        peak_flat = int(np.nanargmax(np.where(mask, initial_image, np.nan)))
        peak_y, peak_x = np.unravel_index(peak_flat, od.shape)
        labelled, count = label(candidate)
        if count and labelled[peak_y, peak_x] != 0:
            component = labelled == labelled[peak_y, peak_x]
            if np.count_nonzero(component) >= 3:
                candidate = component

        weights = np.where(candidate, initial_image, 0.0)
        total = float(np.sum(weights))
        if total <= 0 or np.count_nonzero(weights) < 3:
            weights = np.where(mask, initial_image, 0.0)
            total = float(np.sum(weights))

        if total <= 0:
            return {
                "A": max(peak, 0.01),
                "x0": self.width / 2,
                "y0": self.height / 2,
                "sx": max(self.width / 8, 1),
                "sy": max(self.height / 8, 1),
                "z0": z0,
            }

        x0 = float(np.sum(x * weights) / total)
        y0 = float(np.sum(y * weights) / total)
        sx = float(np.sqrt(np.sum(np.square(x - x0) * weights) / total))
        sy = float(np.sqrt(np.sum(np.square(y - y0) * weights) / total))
        amplitude = (
            float(np.nanmax(initial_image[candidate])) if np.any(candidate) else peak
        )

        return {
            "A": max(amplitude, 0.01),
            "x0": x0,
            "y0": y0,
            "sx": sx,
            "sy": sy,
            "z0": z0,
        }

    @functools.cached_property
    def fit_sampling_step(self):
        """Adaptive two-axis downsampling used by the Gaussian fit."""
        initial = self._fit_initial_values
        configured = max(1, int(self.settings.fit_downsample))

        # Keep roughly six samples across the smaller 2-sigma diameter.
        scale_step = max(
            1,
            int(math.floor(min(initial["sx"], initial["sy"]) / 3.0)),
        )
        return min(configured, scale_step)

    @functools.cached_property
    def fit(self):
        """Fit a robust Gaussian-plus-offset model within the reference beam."""
        y_mg, x_mg = self.xy
        od = self.optical_density
        initial = self._fit_initial_values
        model = Model(ravel(gaussian_2D), independent_vars=["x", "y"])

        model.set_param_hint("A", value=initial["A"], min=0)
        model.set_param_hint(
            "x0",
            value=initial["x0"],
            min=0,
            max=self.width - 1,
        )
        model.set_param_hint(
            "y0",
            value=initial["y0"],
            min=0,
            max=self.height - 1,
        )
        model.set_param_hint(
            "sx",
            value=initial["sx"],
            max=self.width,
        )
        model.set_param_hint(
            "sy",
            value=initial["sy"],
            max=self.height,
        )
        model.set_param_hint(
            "theta",
            value=0,
            min=-np.pi / 2,
            max=np.pi / 2,
            vary=False,
        )
        model.set_param_hint(
            "z0",
            value=initial["z0"],
            min=-1,
            max=1,
            vary=True,
        )

        step = self.fit_sampling_step
        sample_mask = np.zeros_like(self.beam_mask, dtype=bool)
        sample_mask[::step, ::step] = True
        fit_mask = self.beam_mask & sample_mask & np.isfinite(od)

        if np.count_nonzero(fit_mask) < 7:
            fit_mask = self.beam_mask & np.isfinite(od)
        if np.count_nonzero(fit_mask) < 7:
            raise ValueError("Too few illuminated pixels for an absorption-image fit")

        result = model.fit(
            od[fit_mask],
            x=x_mg[fit_mask],
            y=y_mg[fit_mask],
            method="least_squares",
            max_nfev=4000,
            fit_kws={
                "xtol": 1e-7,
                "ftol": 1e-8,
                "gtol": 1e-8,
            },
        )
        return result

    @functools.cached_property
    def best_values(self):
        return self.fit.best_values

    @functools.cached_property
    def phase_space_density(self):
        """
        Calculate phase-space density for a thermal atomic cloud.

        Parameters
        ----------
        N : float
            Total number of atoms in the cloud.
        sigma_x, sigma_y, sigma_z : floats
            Position-space 1/e standard deviations (meters) along x, y, z.

        Returns
        -------
        n : float
            Number density (atoms per cubic meter).
        lambda_db : float
            Thermal de Broglie wavelength (meters).
        PSD : float
            Phase-space density (dimensionless, N λ³ / V).
        """

        sigma_x = self.fit.best_values["sx"] * self.physical_scale
        sigma_y = self.fit.best_values["sy"] * self.physical_scale
        sigma_z = self.fit.best_values["sx"] * self.physical_scale

        # Volume of the cloud assuming Gaussian distribution, 3D
        # V = (2π)^(3/2) σx σy σz
        V = (2 * np.pi) ** (3 / 2) * sigma_x * sigma_y * sigma_z

        # Number density
        n = self.atom_number / V

        # Thermal de Broglie wavelength
        # λ_dB = h / sqrt(2 π m k_B T)
        lambda_db = const.h / np.sqrt(
            2 * np.pi * self.settings.atom_mass * const.k * self.settings.temperature
        )

        # Phase-space density: n * λ_dB^3
        PSD = n * lambda_db**3

        return n, lambda_db, PSD

    @functools.cached_property
    def phase_space_density_1(self):
        """Returns the phase-space density of the cloud."""
        n, lambda_db, PSD = self.phase_space_density
        return PSD

    @functools.cached_property
    def peak_od(self):
        """Returns the peak optical density of the cloud."""
        return self.peak[2]

    @property
    def best_fit(self):
        """Evaluate the complete Gaussian-plus-offset fit on the image grid."""
        return self.eval(x=self.xy[1], y=self.xy[0]).reshape(self.height, self.width)

    @property
    def best_fit_cloud(self):
        """Evaluate only the positive Gaussian cloud component of the fit."""
        return self.best_fit - float(self.best_values.get("z0", 0.0))

    def eval(self, *, x, y):
        """Evaluate the complete Gaussian-plus-offset fit."""
        return self.fit.eval(x=x, y=y)

    def eval_cloud(self, *, x, y):
        """Evaluate only the Gaussian cloud component."""
        return self.eval(x=x, y=y) - float(self.best_values.get("z0", 0.0))

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
        gs_bottom = GridSpec(1, 4, top=0.68, bottom=0.16, **grid_params)  # For OD plot

        # Create all axes in a more compact way
        raw_axes = [fig.add_subplot(gs_top[0, i]) for i in range(3)]
        cax_raw = fig.add_subplot(gs_top[0, 3])
        od_ax = fig.add_subplot(gs_bottom[0, 0:3])
        cax_od = fig.add_axes([0.1, 0.07, 0.75, 0.025])

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
                cmap="viridis",
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

        # Plot the cloud-only OD so the display remains clear even though the
        # fit uses signed OD internally.
        display_od = self.cloud_optical_density
        display_fit = self.best_fit_cloud
        illuminated_values = display_od[self.beam_mask]
        vmax = max(
            float(np.nanpercentile(illuminated_values, 99.9))
            if illuminated_values.size
            else 0,
            float(self.best_values["A"]),
            1e-6,
        )
        vmin = 0.0
        plot_params = {
            "cmap": "viridis",
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
        im1 = od_ax.imshow(display_od, **plot_params)
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

        # show the 1stdev fitted gaussian outline - contour of A/e
        od_ax.contour(
            x_contour,
            y_contour,
            display_fit,
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

        # Show compact fit diagnostics as marginal slices through the fitted center.
        x0_px = self.best_values["x0"]
        y0_px = self.best_values["y0"]
        x0_idx = int(np.clip(np.rint(x0_px), 0, self.width - 1))
        y0_idx = int(np.clip(np.rint(y0_px), 0, self.height - 1))
        x_pixels = np.arange(self.width, dtype=float)
        y_pixels = np.arange(self.height, dtype=float)
        marginal_slices = [
            (
                x_contour,
                display_od[y0_idx, :],
                self.eval_cloud(x=x_pixels, y=np.full(self.width, y0_px)),
                False,
            ),
            (
                y_contour,
                display_od[:, x0_idx],
                self.eval_cloud(x=np.full(self.height, x0_px), y=y_pixels),
                True,
            ),
        ]

        def plot_marginal_slice(axis_values, raw_slice, fit_slice, *, vertical):
            finite_values = np.concatenate([
                raw_slice[np.isfinite(raw_slice)],
                fit_slice[np.isfinite(fit_slice)],
            ])
            if finite_values.size == 0:
                return

            value_min = min(0, np.min(finite_values))
            value_max = np.max(finite_values)
            value_range = value_max - value_min
            if value_range <= 0:
                return

            raw_norm = np.clip((raw_slice - value_min) / value_range, 0, 1)
            fit_norm = np.clip((fit_slice - value_min) / value_range, 0, 1)
            baseline, axis_range = (
                (extent[0], extent[1] - extent[0])
                if vertical
                else (extent[2], extent[3] - extent[2])
            )

            for norm, color, linewidth, zorder in [
                (raw_norm, "white", 1.1, 4),
                (fit_norm, "green", 1.5, 5),
            ]:
                marginal_coords = baseline + norm * 0.1 * axis_range
                args = (
                    (marginal_coords, axis_values)
                    if vertical
                    else (axis_values, marginal_coords)
                )
                od_ax.plot(
                    *args,
                    color=color,
                    linewidth=linewidth,
                    zorder=zorder,
                )

        for axis_values, raw_slice, fit_slice, vertical in marginal_slices:
            plot_marginal_slice(axis_values, raw_slice, fit_slice, vertical=vertical)

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
            orientation="horizontal",
            label="Optical Density",
        )
        cb_od.ax.tick_params(labelsize=8)

        # For Qt integration, draw once to calculate sizes
        fig.canvas.draw_idle()

        textstr = "\n".join((
            rf"Atom number: $\mathbf{{{self.atom_number:.2e}}}$",
            rf"Time of Flight (ms): $\mathbf{{{self.settings.time_of_flight * 1e3:.4g}}}$",
            rf"Peak OD: $\mathbf{{{self.peak[2]:.2f}}}$",
            rf"Centroid (mm): ($\mathbf{{{centroid_mm[0]:.2f}}}$, $\mathbf{{{centroid_mm[1]:.2f}}}$)",
            rf"Peak center (mm): ($\mathbf{{{peak_mm[0]:.2f}}}$, $\mathbf{{{peak_mm[1]:.2f}}}$)",
            rf"$\sigma_x$ (mm): $\mathbf{{{self.best_values['sx'] * scale_mm:.2f}}}$",
            rf"$\sigma_y$ (mm): $\mathbf{{{self.best_values['sy'] * scale_mm:.2f}}}$",
            rf"Phase-space density: $\mathbf{{{self.phase_space_density[2]:.2e}}}$",
            rf"$\lambda_{{\mathrm{{dB}}}}$ (m): $\mathbf{{{self.phase_space_density[1]:.2e}}}$",
            rf"Peak density (atoms/cm$^3$): $\mathbf{{{self.phase_space_density[0] * 1e-6:.2e}}}$",
        ))
        od_ax.text(
            1.1,
            0.5,
            textstr,
            transform=od_ax.transAxes,
            fontsize=9,
            verticalalignment="center",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="wheat", alpha=0.5),
        )

        plt.tight_layout()

        return fig, axes + [cax_raw, cax_od]
