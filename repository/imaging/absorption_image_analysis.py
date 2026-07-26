from scipy.optimize import curve_fit
import numpy as np
from matplotlib import pyplot as plt
from ndscan.experiment import (
    OpaqueChannel,
    make_fragment_scan_exp,
)
from ndscan.experiment.default_analysis import CustomAnalysis
from repository.imaging.absorption_image import AbsorptionImageExpFrag
from submodules.ndscan.ndscan.experiment.result_channels import FloatChannel


class AnalysisResultExpFrag(AbsorptionImageExpFrag):
    """Analysis for absorption imaging of MOT expansion"""

    def get_default_analyses(self):
        return [
            CustomAnalysis(
                [self.expansion_time],
                self.Fits,
                [
                    OpaqueChannel("Expansion_time_unique"),
                    OpaqueChannel("mean_sigma_x"),
                    OpaqueChannel("std_sigma_x"),
                    OpaqueChannel("mean_sigma_y"),
                    OpaqueChannel("std_sigma_y"),
                    OpaqueChannel("diam_fit_x"),
                    OpaqueChannel("fit_time_x"),
                    OpaqueChannel("diam_fit_y"),
                    OpaqueChannel("fit_time_y"),
                    FloatChannel("temperature_x"),
                    FloatChannel("temperature_x_err"),
                    FloatChannel("temperature_y"),
                    FloatChannel("temperature_y_err"),
                    OpaqueChannel("diam_0_x"),
                    OpaqueChannel("diam_0_y"),
                    OpaqueChannel("diam_0_x_err"),
                    OpaqueChannel("diam_0_y_err"),
                    OpaqueChannel("pixel_calibration_fit"),
                    OpaqueChannel("t_fit_pixel"),
                    OpaqueChannel("pixel_number"),
                    OpaqueChannel("pixel_number_err"),
                    OpaqueChannel("pixel_size"),
                    OpaqueChannel("pixel_size_err"),
                ],
            )
        ]

    def Fits(self, axis_values, result_values, analysis_result):
        def Temperature_fit():
            # Get expansion time data
            Expansion_time = axis_values[self.expansion_time]

            # get the standard deviation data for the x and y direction
            sigmax = result_values[self.sigmax_mm]  # Get raw data
            sigmay = result_values[self.sigmay_mm]  # Get raw data

            # Convert to SI units (meters and seconds)
            Expansion_time = np.array(Expansion_time)  # Convert ms to s
            sigma_x = np.array(sigmax) * 1e-3  # Convert mm to m
            sigma_y = np.array(sigmay) * 1e-3  # Convert mm to m

            #  Get the average over repeats at each expansion time
            unique_times = np.unique(Expansion_time)
            mean_sigma_x = np.zeros_like(unique_times)
            mean_sigma_y = np.zeros_like(unique_times)

            for i, t in enumerate(unique_times):
                idx = Expansion_time == t
                mean_sigma_x[i] = np.mean(sigma_x[idx])
                mean_sigma_y[i] = np.mean(sigma_y[idx])
                std_sigma_x = np.std(sigma_x[idx])
                std_sigma_y = np.std(sigma_y[idx])

            def analyze_diameter(Expansion_time, sigma, std_sigma, diametertype="x"):
                """
                Perform temperature fit + plotting for diameter data.

                Parameters:
                    Expansion_time : list or array
                    sigma          : list or array (diameter values)
                    diametertype   : "x", "y", or "other"

                Returns:
                    t_fit (list), d_fit (list)
                """

                # --- Convert to NumPy arrays FIRST (fixes your earlier errors) ---
                Expansion_time = np.array(Expansion_time)
                sigma = np.array(sigma)

                # --- Constants ---
                kB = 1.380649e-23  # Boltzmann constant (J/K)
                m = 1.45e-25  # Mass (kg)

                # --- Model ---
                def model(t, d0, T):
                    return np.sqrt(d0**2 + (kB * T * t**2) / m)

                # --- Fit ---
                bounds = ([0, 0], [np.inf, np.inf])
                p0 = [1e-3, 50e-6]

                # Fit the model to the data
                if np.any(np.isnan(sigma)) or np.any(np.isnan(Expansion_time)):
                    print("Warning: NaN values detected in data. Skipping fit.")
                    return [], []
                elif np.any(std_sigma > 0):  # check if one point has a repeat
                    safe_err = np.where(
                        std_sigma > 0, std_sigma, np.min(std_sigma[std_sigma > 0])
                    )
                    popt, pcov = curve_fit(
                        model,
                        Expansion_time,
                        sigma,
                        p0=p0,
                        bounds=bounds,
                        sigma=safe_err,
                        absolute_sigma=True,
                    )
                else:
                    popt, pcov = curve_fit(
                        model, Expansion_time, sigma, p0=p0, bounds=bounds
                    )

                d0_fit, T_fit = popt
                d0_err, T_err = np.sqrt(np.diag(pcov))

                # --- Fit curve ---
                # d is the diameter, t is the expansion time
                t_fit = np.linspace(min(Expansion_time), max(Expansion_time), 300)
                d_fit = model(t_fit, *popt)

                perr = np.sqrt(np.diag(pcov))
                d_fit_upper = model(t_fit, *(popt + perr))
                d_fit_lower = model(t_fit, *(popt - perr))

                # =======================
                # MAIN FIT PLOT
                # =======================
                plt.figure(figsize=(6, 4))

                plt.fill_between(
                    t_fit * 1e6,
                    d_fit_lower * 1e6,
                    d_fit_upper * 1e6,
                    color="gray",
                    alpha=0.4,
                    label="Confidence Interval",
                )

                plt.plot(t_fit * 1e6, d_fit * 1e6, "r-", label="Fit")
                if np.any(std_sigma > 0):
                    plt.errorbar(
                        Expansion_time * 1e6,
                        sigma * 1e6,
                        yerr=std_sigma * 1e6,
                        fmt="o",
                        label="Data (mean ± std)",
                        capsize=3,
                    )
                else:
                    plt.plot(
                        Expansion_time * 1e6,
                        sigma * 1e6,
                        "o",
                        label="Data",
                    )

                plt.xlabel("TOF (μs)")

                ylabel = (
                    "σₓ (μm)"
                    if diametertype == "x"
                    else "σᵧ (μm)"
                    if diametertype == "y"
                    else "Diameter (μm)"
                )
                plt.ylabel(ylabel)

                title = (
                    "Temperature (X direction)"
                    if diametertype == "x"
                    else "Temperature (Y direction)"
                    if diametertype == "y"
                    else "Temperature Fit"
                )
                plt.title(title)

                fit_text = (
                    f"$d_0$ = {d0_fit * 1e6:.2f} ± {d0_err * 1e6:.2f} μm\n"
                    f"T = {T_fit * 1e6:.2f} ± {T_err * 1e6:.2f} μK"
                )

                plt.gca().text(
                    0.05,
                    0.95,
                    fit_text,
                    transform=plt.gca().transAxes,
                    verticalalignment="top",
                    bbox=dict(facecolor="white", alpha=0.7),
                )

                plt.legend()
                plt.grid(True)
                plt.tight_layout()
                plt.show()

                # =======================
                # RESIDUALS
                # =======================
                residuals = sigma - model(Expansion_time, *popt)

                plt.figure(figsize=(4.5, 3.5))
                plt.plot(Expansion_time * 1e6, residuals * 1e6, "o")
                plt.axhline(0, color="red", linestyle="--")
                plt.xlabel("TOF (μs)")
                plt.ylabel("Residuals (μm)")
                plt.title("Fit Residuals")
                plt.grid(True)
                plt.tight_layout()
                plt.show()

                # =======================
                # HISTOGRAM
                # =======================
                plt.figure(figsize=(4.5, 3.5))
                plt.hist(residuals * 1e6, bins=10, edgecolor="black")
                plt.xlabel("Residuals (μm)")
                plt.ylabel("Frequency")
                plt.title("Histogram of Residuals")
                plt.grid(True)
                plt.tight_layout()
                plt.show()

                # --- Print results ---
                print(f"d0 = {d0_fit * 1e6:.6f} ± {d0_err * 1e6:.6f} μm")
                print(f"T  = {T_fit * 1e6:.6f} ± {T_err * 1e6:.6f} μK")

                # --- Convert for output (ndscan safe) ---
                t_fit_out = t_fit.tolist()
                d_fit_out = (d_fit * 1e3).tolist()  # mm
                return t_fit_out, d_fit_out, T_fit, T_err, d0_fit, d0_err

            t_fit_out_x, d_fit_out_x, T_fit_x, T_err_x, d0_fit_x, d0_err_x = (
                analyze_diameter(
                    unique_times, mean_sigma_x, std_sigma_x, diametertype="x"
                )
            )
            t_fit_out_y, d_fit_out_y, T_fit_y, T_err_y, d0_fit_y, d0_err_y = (
                analyze_diameter(
                    unique_times, mean_sigma_y, std_sigma_y, diametertype="y"
                )
            )

            # Add raw mean and std values
            analysis_result["Expansion_time_unique"].push(unique_times)
            analysis_result["mean_sigma_x"].push(mean_sigma_x)
            analysis_result["std_sigma_x"].push(std_sigma_x)
            analysis_result["mean_sigma_y"].push(mean_sigma_y)
            analysis_result["std_sigma_y"].push(std_sigma_y)

            # Add fit values to the analysis result
            analysis_result["diam_fit_x"].push(d_fit_out_x)
            analysis_result["fit_time_x"].push(t_fit_out_x)
            analysis_result["diam_fit_y"].push(d_fit_out_y)
            analysis_result["fit_time_y"].push(t_fit_out_y)

            # Add the temperature values to the analysis result
            analysis_result["temperature_x"].push(T_fit_x)
            analysis_result["temperature_y"].push(T_fit_y)
            analysis_result["temperature_x_err"].push(T_err_x)
            analysis_result["temperature_y_err"].push(T_err_y)
            analysis_result["diam_0_x"].push(d0_fit_x)
            analysis_result["diam_0_y"].push(d0_fit_y)
            analysis_result["diam_0_x_err"].push(d0_err_x)
            analysis_result["diam_0_y_err"].push(d0_err_y)

            return None

        Temperature_fit()

        def Pixel_callibration_fit():
            Expansion_time = axis_values[self.expansion_time]
            pixel_number_vertical_data = result_values[self.gaussian_fit_centre_y]

            # convert to numpy arrays
            Expansion_time = np.array(Expansion_time)
            pixel_number_vertical_data = np.array(pixel_number_vertical_data)

            # sort t_data and pixel data together
            sorted_indices = np.argsort(Expansion_time)
            Expansion_time = Expansion_time[sorted_indices]
            pixel_number_vertical_data = pixel_number_vertical_data[sorted_indices]

            # return index of some value in t_data_sorted
            def get_index_of_value(value, t_data_sorted):
                try:
                    return np.where(t_data_sorted == value)[0][0]
                except IndexError:
                    return -1

            # pixel data sorted
            pixel_data_sorted = pixel_number_vertical_data[np.argsort(Expansion_time)]

            pixel_data_sorted = -(pixel_data_sorted - np.mean(pixel_data_sorted))

            g = 9.81  # Acceleration due to gravity (m/s^2)

            def model_pixel_calibration(t, y0, s):
                return y0 + (1 / 2) * t**2 * g / s

            # Initial GUESS
            y0_initial = 0
            s_initial = 2e-6

            # Fit your existing data
            popt_pixel, pcov_pixel = curve_fit(
                model_pixel_calibration,
                Expansion_time,
                pixel_data_sorted,
                p0=[y0_initial, s_initial],
            )
            y0_fit = popt_pixel[0]
            y0_err = np.sqrt(np.diag(pcov_pixel))[0]
            s_fit = popt_pixel[1]
            s_err = np.sqrt(np.diag(pcov_pixel))[1]

            # Print results
            print(f"y0 = {y0_fit:.7f} ± {y0_err:.7f} pixels")
            print(f"s = {s_fit * 1e6:.7f} ± {s_err * 1e6:.7f} μm")

            # Plot pixel calibration
            plt.plot(Expansion_time * 1e3, pixel_data_sorted, "o", label="data")
            plt.plot(
                Expansion_time * 1e3,
                model_pixel_calibration(Expansion_time, *popt_pixel),
                label="fit",
            )
            plt.xlabel("TOF (ms)")
            plt.ylabel("Peak of gaussian fit Y0 (pixels)")
            plt.legend()
            plt.grid(True)

            fit_text = (
                f"pixel(t=0) = {y0_fit:.2f} ± {y0_err:.2f} pixels\ns = {s_fit * 1e6:.2f} ±"
                f" {s_err * 1e6:.2f} μm"
            )
            plt.gca().text(
                0.05,
                0.95,
                fit_text,
                transform=plt.gca().transAxes,
                fontsize=10,
                verticalalignment="top",
                bbox=dict(facecolor="white", alpha=0.5, edgecolor="black"),
            )
            plt.tight_layout()
            plt.title("Pixel Calibration using MOT after PGC")
            plt.show()

            # confidence interval for pixel calibration
            # Calculate the standard deviation of the fit
            perr_pixel = np.sqrt(np.diag(pcov_pixel))
            # Generate points for the fit line
            t_fit_pixel = np.linspace(min(Expansion_time), max(Expansion_time), 100)
            pixel_fit = model_pixel_calibration(t_fit_pixel, *popt_pixel)
            # Calculate the upper and lower bounds of the confidence interval
            pixel_fit_upper = model_pixel_calibration(
                t_fit_pixel, *(popt_pixel + perr_pixel)
            )
            pixel_fit_lower = model_pixel_calibration(
                t_fit_pixel, *(popt_pixel - perr_pixel)
            )
            # Plot the fit line and confidence interval
            plt.fill_between(
                t_fit_pixel * 1e3,
                pixel_fit_lower,
                pixel_fit_upper,
                color="gray",
                alpha=0.5,
                label="Confidence Interval",
            )
            plt.plot(t_fit_pixel * 1e3, pixel_fit, "r-", label="Fit Line")
            plt.plot(Expansion_time * 1e3, pixel_data_sorted, "o", label="Data")
            plt.xlabel("TOF (ms)")
            plt.ylabel("Peak of gaussian fit y0 (pixels)")
            plt.title("Pixel Calibration with Confidence Interval")
            plt.legend()
            plt.grid()
            plt.tight_layout()
            plt.show()

            # plot the residuals of the pixel calibration
            residuals_pixel = pixel_data_sorted - model_pixel_calibration(
                Expansion_time, *popt_pixel
            )
            plt.figure(figsize=(4, 3))
            plt.plot(Expansion_time * 1e3, residuals_pixel, "o")
            plt.axhline(0, color="r", linestyle="--")
            plt.xlabel("TOF (ms)")
            plt.ylabel("Residuals (pixels)")
            plt.title("Residuals of the Pixel Calibration Fit")
            plt.grid()
            plt.show()
            return t_fit_pixel, pixel_fit, y0_fit, y0_err, s_fit, s_err

        t_fit_pixel, pixel_fit, y0_fit, y0_err, s_fit, s_err = Pixel_callibration_fit()

        # Save reuslts of pixel calibration
        analysis_result["pixel_calibration_fit"].push(pixel_fit)
        analysis_result["t_fit_pixel"].push(t_fit_pixel)
        analysis_result["pixel_number"].push(y0_fit)
        analysis_result["pixel_number_err"].push(y0_err)
        analysis_result["pixel_size"].push(s_fit)
        analysis_result["pixel_size_err"].push(s_err)

        return None


AnalysisResult = make_fragment_scan_exp(AnalysisResultExpFrag)
