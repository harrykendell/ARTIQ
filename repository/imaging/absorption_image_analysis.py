from scipy.optimize import curve_fit
import numpy as np
from matplotlib import pyplot as plt
from ndscan.experiment import (OpaqueChannel,
    make_fragment_scan_exp,
)
from ndscan.experiment.default_analysis import CustomAnalysis
from repository.imaging.absorption_image import AbsorptionImageExpFrag
 
 
class analysis_result(AbsorptionImageExpFrag):
    """Analysis for absorption imaging of MOT expansion"""
 
    def get_default_analyses(self):
        return [
            CustomAnalysis(
                [self.expansion_time],
                self.Temperature,
                [OpaqueChannel("fit_t"), OpaqueChannel("fit_d")],
            )
        ]
 
    def Temperature(self, axis_values, result_values, analysis_result):
 
        t_data_sorted = axis_values[self.expansion_time]
        # Get expansion time data
        d_data_sorted = result_values[self.sigmax_mm]  # Get atom number data
        diametertype = "x"  # or "y" depending on which diameter you are analyzing
        # Convert to SI units (meters and seconds)
        t_data_sorted = np.array(t_data_sorted)  # Convert ms to s
        d_data_sorted = np.array(d_data_sorted) * 1e-3  # Convert mm to m
        print("t_data_sorted (s):", t_data_sorted)
        print("d_data_sorted (m):", d_data_sorted)
 
        # Constants
        kB = 1.380649e-23  # Boltzmann constant (J/K)
        m = 1.45e-25  # Mass (kg)
 
        # Model function
        def model(t, d0, T):
            return np.sqrt(d0**2 + (kB * T * t**2) / m)
 
        bounds = ([0, 0], [np.inf, np.inf])
        p0 = [1e-3, 50e-6]  # Initial guess
 
        popt, pcov = curve_fit(model, t_data_sorted, d_data_sorted, p0=p0, bounds=bounds)
        d0_fit, T_fit = popt
        d0_err, T_err = np.sqrt(np.diag(pcov))
 
 
        t_data_sorted = np.array(t_data_sorted)
        d_data_sorted = np.array(d_data_sorted)
 
        # --- Combined Plot: Data + Fit + Confidence Interval ---
        plt.figure(figsize=(6, 4))
 
        t_fit = np.linspace(min(t_data_sorted), max(t_data_sorted), 300)
        d_fit = model(t_fit, *popt)
        perr = np.sqrt(np.diag(pcov))
        d_fit_upper = model(t_fit, *(popt + perr))
        d_fit_lower = model(t_fit, *(popt - perr))
 
        plt.fill_between(
            t_fit * 1e6,
            d_fit_lower * 1e6,
            d_fit_upper * 1e6,
            color="gray",
            alpha=0.4,
            label="Confidence Interval",
        )
        plt.plot(t_fit * 1e6, d_fit * 1e6, "r-", label="Fit")
        plt.plot(t_data_sorted * 1e6, d_data_sorted * 1e6, "o", color="blue", label="Data")
 
        plt.xlabel("TOF (μs)", fontsize=12)
        ylabel = (
            "σₓ (μm)"
            if diametertype == "x"
            else "σᵧ (μm)"
            if diametertype == "y"
            else "Diameter (μm)"
        )
        plt.ylabel(ylabel, fontsize=12)
 
        if diametertype == "x":
            plt.title("MOT Temperature (X direction) after PGC", fontsize=13)
        elif diametertype == "y":
            plt.title("MOT Temperature (Y direction) after PGC", fontsize=13)
        else:
            plt.title("MOT Temperature Fit", fontsize=13)
 
        fit_text = (
            f"$d_0$ = {d0_fit * 1e6:.2f} ± {d0_err * 1e6:.2f} μm\n"
            f"T = {T_fit * 1e6:.2f} ± {T_err * 1e6:.2f} μK"
        )
        plt.gca().text(
            0.05,
            0.95,
            fit_text,
            transform=plt.gca().transAxes,
            fontsize=10,
            verticalalignment="top",
            bbox=dict(facecolor="white", edgecolor="black", alpha=0.7),
        )
 
        plt.legend(fontsize=10)
        plt.grid(True, linestyle="--", alpha=0.6)
        plt.tight_layout()
        plt.show()
 
        # --- Output Fit Results ---
        print(f"d0 = {d0_fit * 1e6:.6f} ± {d0_err * 1e6:.6f} μm")
        print(f"T  = {T_fit * 1e6:.6f} ± {T_err * 1e6:.6f} μK")
 
        # --- Residuals Plot ---
        residuals = d_data_sorted - model(t_data_sorted, *popt)
 
        # convert to numpy array every data object is a list of one element
    
        residuals = np.array(residuals)
 
 
        plt.figure(figsize=(4.5, 3.5))
        plt.plot(t_data_sorted * 1e6, residuals * 1e6, "o", color="black")
        plt.axhline(0, color="red", linestyle="--")
        plt.xlabel("TOF (μs)", fontsize=11)
        plt.ylabel("Residuals (μm)", fontsize=11)
        plt.title("Fit Residuals", fontsize=12)
        plt.grid(True, linestyle="--", alpha=0.6)
        plt.tight_layout()
        plt.show()
 
        # --- Histogram of Residuals ---
        plt.figure(figsize=(4.5, 3.5))
        plt.hist(residuals * 1e6, bins=10, edgecolor="black", color="gray")
        plt.xlabel("Residuals (μm)", fontsize=11)
        plt.ylabel("Frequency", fontsize=11)
        plt.title("Histogram of Residuals", fontsize=12)
        plt.grid(True, linestyle="--", alpha=0.6)
        plt.tight_layout()
        plt.show()
 
        #convert to units for pushing to OpaqueChannel
        d_fit=d_fit * 1e3  # Convert back to mm for pushing to OpaqueChannel
 
        t_fit = t_fit.tolist()  # Convert to list for pushing to OpaqueChannel
        d_fit = d_fit.tolist()  # Convert to list for pushing to OpaqueChannel
 
        analysis_result["fit_t"].push(t_fit)
        analysis_result["fit_d"].push(d_fit)
    
        return None
 
 
analysis_result = make_fragment_scan_exp(analysis_result)