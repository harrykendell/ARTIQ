from artiq.coredevice.core import Core
from artiq.experiment import kernel, rpc, delay, parallel, now_mu
from artiq.language.units import s, ms, us, MHz
from device_db import server_addr

from ndscan.experiment import ExpFragment, make_fragment_scan_exp, FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from repository.imaging.PCO_Camera import PcoCamera
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.models.devices import SUServoedBeam, VDrivenSupply

import numpy as np
from scipy.ndimage import gaussian_filter
import logging
from lmfit import Model
import functools


class AbsorptionImageExpFrag(ExpFragment):
    """
    Absorption imaging of MOT expansion
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")

        self.setattr_fragment("pco_camera", PcoCamera, num_images=3)
        self.pco_camera: PcoCamera
        self.setattr_param_rebind(
            "exposure_time", self.pco_camera, "exposure_time", default=1 * ms
        )
        self.exposure_time: FloatParamHandle

        self.setattr_fragment(
            "coil_setter",
            SetAnalogCurrentSupplies,
            VDrivenSupply["X1", "X2"],
            init=False,
        )
        self.coil_setter: SetAnalogCurrentSupplies

        self.setattr_fragment(
            "mot_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["MOT"]],
        )
        self.mot_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_fragment(
            "img_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["IMG"]],
        )
        self.img_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_param(
            "load_time",
            FloatParam,
            "Time to load the MOT",
            default=10.0 * s,
            unit="s",
        )
        self.load_time: FloatParamHandle

        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=5.0 * ms,
            min=1.0 * us,
            unit="ms",
        )
        self.expansion_time: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.reset()

        self.coil_setter.turn_off()  # make sure we unload MOT
        delay(100 * ms)

        # load the MOT
        self.mot_beam_setter.turn_beams_on()
        self.img_beam_setter.turn_beams_off()
        self.coil_setter.set_defaults()
        delay(self.load_time.get())

        # release MOT and propagate cloud - we can't shutter as tof may be less than the delay
        with parallel:
            self.coil_setter.turn_off()
            self.mot_beam_setter.turn_beams_off(ignore_shutters=True)
        delay(self.expansion_time.get())

        # image cloud
        with parallel:
            self.img_beam_setter.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam_setter.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME)

        # make sure the mot has cleared
        delay(100 * ms)

        # reference image
        with parallel:
            self.img_beam_setter.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam_setter.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME)

        # background image
        self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        delay(self.pco_camera.BUSY_TIME)

        # leave the MOT to reload
        self.coil_setter.set_defaults()
        self.mot_beam_setter.turn_beams_on()
        self.img_beam_setter.turn_beams_off()

        self.core.wait_until_mu(now_mu())
        self.update_images()

    @rpc(flags={"async"})
    def update_images(self):
        images = self.pco_camera.retrieve_images(
            roi=self.pco_camera.FULL_ROI, timeout=10 * s
        )
        if images is None:
            raise RuntimeError("Failed to retrieve images from camera")

        try:
            abs_img = AbsImage(images[0], images[1], images[2])
            od = abs_img.optical_density
            fitted = abs_img.best_fit
            num = abs_img.atom_number

            self.set_dataset("Images.absorption.OD", od, broadcast=True)
            self.ccb.issue(
                "create_applet",
                f"Optical Density ({num:.2e} atoms)",
                f"${{artiq_applet}}image Images.absorption.OD --server {server_addr}",
            )

            self.set_dataset("Images.absorption.Fit", fitted, broadcast=True)
            self.ccb.issue(
                "create_applet",
                "Optical Density Fit",
                f"${{artiq_applet}}image Images.absorption.Fit --server {server_addr}",
            )
            self.set_dataset("Images.absorption.NumAtoms", num, broadcast=True)
        except ValueError as e:
            logging.error(f"Failed to process images: {e}")

        for num, img_name in enumerate(["TOF", "REF", "BG"]):
            # save for applet
            self.set_dataset(
                f"Images.absorption.{img_name}", images[num], broadcast=True
            )

            self.ccb.issue(
                "create_applet",
                f"{img_name}",
                f"${{artiq_applet}}image Images.absorption.{img_name} --server {server_addr}",
            )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)


def gaussian_2D(x, y, A, x0, y0, sx, sy, theta=0, z0=0):
    """Takes a meshgrid of x, y and returns the gaussian computed across all values.
    See https://en.wikipedia.org/wiki/Gaussian_function#Two-dimensional_Gaussian_function
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

    def __init__(
        self,
        data,
        ref,
        bg,
        wavelength=780.24 * nm,
        detuning=0 * MHz,
        linewidth=6.065 * MHz,
        pixel_size=6.45 * um,
        magnification=None,
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
        self.data_image = data
        self.ref_image = ref
        self.bg_image = bg

        self.height = data.shape[0]
        self.width = data.shape[1]
        self.xy = np.mgrid[0 : self.height, 0 : self.width]

        self.wavelength = wavelength
        self.detuning = detuning
        self.linewidth = linewidth
        self.pixel_size = pixel_size

        if magnification is None:
            # NB for now 50mm lens at 150mm distance focuses to 75mm away
            # self.magnification = 75 / 150 = 0.5
            raise ValueError(
                "Please set magnification for the PCO camera\nNB: For now\
                             a 50mm lens at 150mm focuses to 75mm away, so set to 0.5"
            )
        self.magnification = magnification

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
        """Returns the beam and dark-field compensated transmission image. Dark-field is subtracted
        from both the atom image and the beam image, and the atom image is divided by the beam
        image, giving the transmission t^2. The values should optimally lie in the range of [0, 1]
        but can realistically be in the range of [-0.1, 1.5] due to noise and beam variation across
        images."""
        logging.info("Performing background subtraction")
        atoms = np.subtract(self.data_image, self.bg_image)
        light = np.subtract(self.ref_image, self.bg_image)

        # If the light data is below some threshold, we assume that any
        # atom data at this location is invalid and treat as if no transmission.
        # The threshold value was selected experimentally
        threshold = 100
        transmission = np.divide(atoms, light, where=light > threshold)
        transmission[light <= threshold] = 1
        np.clip(transmission, a_min=0, a_max=1, out=transmission)

        if np.min(transmission) == 1:
            raise ValueError(
                "Transmission is all 1s, there doesn't appear to be an atom cloud"
            )
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

        return (
            (area / sigma) * np.sum(optical_density) / 0.866
        )  # Divide by 1.5-sigma area

    @functools.cached_property
    def peak(self):
        """Returns x, y, z of brightest pixel in absorption"""
        y, x = np.unravel_index(
            np.argmax(self.optical_density), self.optical_density.shape
        )
        z = self.optical_density[x, y]

        print(f"Peak: {x}, {y}, {z}")
        return x, y, z

    @functools.cached_property
    def centroid(self):
        """Returns x, y, z of the centroid of the absorption image"""
        y, x = self.xy
        A = np.sum(self.optical_density)
        x_c = int(np.sum(x * self.optical_density) / A)
        y_c = int(np.sum(y * self.optical_density) / A)
        z_c = self.optical_density[y_c, x_c]
        print(f"Centroid: {x_c}, {y_c}, {z_c}")
        return x_c, y_c, z_c

    @functools.cached_property
    def sigma_mask(self):
        """Returns a numpy mask of pixels within the 2-sigma limit of the model (no ROI)"""
        bp_2D = self.best_values
        x0, y0, a, b, theta = (bp_2D[k] for k in ("x0", "y0", "sx", "sy", "theta"))
        y, x = np.ogrid[0 : self.height, 0 : self.width]

        # https://math.stackexchange.com/a/434482
        maj_axis = np.square((x - x0) * np.cos(theta) - (y - y0) * np.sin(theta))
        min_axis = np.square((x - x0) * np.sin(theta) + (y - y0) * np.cos(theta))
        bound = 4.343  # chi2.ppf(0.886, df=2)

        array = np.zeros(self.data_image.shape, dtype="bool")
        array[maj_axis / np.square(a) + min_axis / np.square(b) <= bound] = True
        return array

    @functools.cached_property
    def fit(self):
        """Fits a 2D Gaussian against the absorption."""
        logging.info("Running 2D fit...")

        x_mg, y_mg = self.xy
        model = Model(ravel(gaussian_2D), independent_vars=["x", "y"])

        x_c, y_c, A = self.centroid
        model.set_param_hint("A", value=A, min=0, max=6)
        model.set_param_hint("x0", value=x_c, min=0, max=self.width)
        model.set_param_hint("y0", value=y_c, min=0, max=self.height)

        model.set_param_hint("sx", value=self.width / 4, min=1, max=self.width)
        model.set_param_hint("sy", value=self.height / 4, min=1, max=self.height)
        model.set_param_hint("theta", value=0, min=-np.pi / 4, max=np.pi / 4, vary=True)
        model.set_param_hint("z0", value=0, min=-1, max=1, vary=True)

        result = model.fit(
            np.ravel(self.optical_density[::5]),
            x=x_mg[::5],
            y=y_mg[::5],
            max_nfev=1000,
            # scale_covar=False,
            fit_kws={"xtol": 1e-7},
        )
        logging.info(result.fit_report())

        if abs(result.summary()["rsquared"]) < 0.9:
            logging.error(f"Poor fit: r^2 = {result.summary()['rsquared']}")
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
        """Evaluates the fit at the given coordinates (proxy for ModelResult)."""
        return self.fit.eval(x=y, y=x)

    def plot(self):
        """Plots the optical density and the best fit in real space units."""
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        # Create figure with two subplots sharing x and y axes
        fig, ax = plt.subplots(1, 2, figsize=(10, 5), sharex=True, sharey=True)

        # Convert to real space units (mm)
        scale_mm = self.physical_scale * 1e3
        extent = [0, self.width * scale_mm, 0, self.height * scale_mm]

        # Format ticks to show mm with 1 decimal place
        formatter = FuncFormatter(lambda x, pos: f"{x:.1f}")

        # Get common colormap range
        vmin = min(np.min(self.optical_density), np.min(self.best_fit))
        vmax = max(np.max(self.optical_density), np.max(self.best_fit))

        # Common plot parameters
        plot_params = {
            "cmap": "grey",
            "origin": "lower",
            "extent": extent,
            "vmin": vmin,
            "vmax": vmax,
        }

        # Convert points to real space
        centroid_mm = (self.centroid[0] * scale_mm, self.centroid[1] * scale_mm)
        peak_mm = (self.peak[0] * scale_mm, self.peak[1] * scale_mm)

        # Get fit center coordinates in real space
        fit_center_mm = (
            self.best_values["x0"] * scale_mm,
            self.best_values["y0"] * scale_mm,
        )

        # Create contour coordinates
        x_contour = np.linspace(extent[0], extent[1], self.width)
        y_contour = np.linspace(extent[2], extent[3], self.height)

        # Plot both images with appropriate markers
        # Left plot: Optical Density with measured centroid/peak
        ax[0].imshow(self.optical_density, **plot_params)
        ax[0].contour(
            x_contour, y_contour, self.sigma_mask, colors="green", linewidths=0.5
        )
        ax[0].scatter(centroid_mm[0], centroid_mm[1], color="red", label="Centroid")
        ax[0].scatter(peak_mm[0], peak_mm[1], color="blue", label="Peak")
        ax[0].set_title("Optical Density")

        # Right plot: Best Fit with fit center
        im1 = ax[1].imshow(self.best_fit, **plot_params)
        ax[1].contour(
            x_contour, y_contour, self.sigma_mask, colors="green", linewidths=0.5
        )
        ax[1].scatter(
            fit_center_mm[0], fit_center_mm[1], color="red", label="Fit Center"
        )
        ax[1].set_title("Best Fit")

        for i in (0, 1):
            ax[i].legend()
            ax[i].set_xlabel("x position (mm)")
            ax[i].set_ylabel("y position (mm)")
            ax[i].xaxis.set_major_formatter(formatter)
            ax[i].yaxis.set_major_formatter(formatter)

        # Add shared colorbar
        cbar_ax = fig.add_axes([0.92, 0.15, 0.02, 0.7])
        cbar = fig.colorbar(im1, cax=cbar_ax)
        cbar.set_label("Optical Density")

        plt.show()
        return fig, ax

    @staticmethod
    def fake():
        """
        Creates a randomised fake AbsImage object for testing purposes.

        Large gaussian imaging beam multiplied by a smaller (sum of gaussians) atom shadow
        """
        height, width = 1000, 1300
        posx = np.random.uniform(width / 3, width * 2 / 3)
        posy = np.random.uniform(height / 3, height * 2 / 3)
        print(f"Fake atom cloud at {posx}, {posy}")
        x, y = np.mgrid[0:height, 0:width]
        fake_ref = gaussian_2D(
            x,
            y,
            A=np.random.uniform(1000, 16000),
            x0=posx,
            y0=posy,
            sx=np.random.uniform(width / 2, width / 4),
            sy=np.random.uniform(height / 2, height / 4),
            theta=np.random.uniform(0, np.pi),
        )

        sx = np.random.uniform(width / 20, width / 5)
        sy = np.random.uniform(height / 20, height / 5)
        atom_cloud = fake_ref * 0
        for _ in range(1):
            atom_cloud += gaussian_2D(
                x,
                y,
                A=np.random.uniform(-0.9, -0.1),
                x0=posx * (1 + np.random.uniform(-0.2, 0.2)),
                y0=posy * (1 + np.random.uniform(-0.2, 0.2)),
                sx=sx * (1 + np.random.uniform(-0.2, 0.2)),
                sy=sy * (1 + np.random.uniform(-0.2, 0.2)),
                theta=np.random.uniform(0, np.pi),
                z0=1,
            )

        fake_data = np.multiply(fake_ref, atom_cloud / 1)

        # add some noise
        noise = 20
        fake_ref += np.random.normal(0, noise, size=fake_ref.shape)
        fake_data += np.random.normal(0, noise, size=fake_data.shape)
        fake_bg = np.random.normal(0, noise, size=fake_ref.shape)

        return AbsImage(
            data=fake_data,
            ref=fake_ref,
            bg=fake_bg,
            magnification=0.5,
        )
