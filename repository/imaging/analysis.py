import logging

import numpy as np
from scipy import constants

logger = logging.getLogger(__name__)
RB87_MASS = 86.909180520 * constants.atomic_mass


def fit_temperature(times, sigma_px, pixel_size):
    """Fit sigma squared against TOF squared."""
    times = np.asarray(times, dtype=float)
    sigma_px = np.asarray(sigma_px, dtype=float)
    valid = np.isfinite(times) & np.isfinite(sigma_px) & (times >= 0) & (sigma_px > 0)
    times = times[valid]
    sigma_px = sigma_px[valid]
    if times.size < 3 or np.unique(times).size < 2:
        return None

    try:
        coefficients, covariance = np.polyfit(times**2, sigma_px**2, 1, cov=True)
    except (ValueError, np.linalg.LinAlgError):
        return None
    sigma_v_px_squared, sigma0_px_squared = coefficients
    if (
        not np.all(np.isfinite(coefficients))
        or sigma0_px_squared < 0
        or sigma_v_px_squared < 0
    ):
        return None

    temperature = RB87_MASS * sigma_v_px_squared * pixel_size**2 / constants.Boltzmann

    slope_variance = covariance[0, 0]
    if np.isfinite(slope_variance) and sigma_v_px_squared > 0:
        temperature_error = temperature * np.sqrt(slope_variance) / sigma_v_px_squared
    else:
        temperature_error = np.nan

    return {
        "fit_params": (sigma0_px_squared, sigma_v_px_squared),
        "sigma0": np.sqrt(sigma0_px_squared) * pixel_size,
        "temperature": temperature,
        "temperature_error": temperature_error,
    }


def fit_gravity(times, position_y_px):
    """Infer an object-plane pixel scale from vertical free fall."""
    times = np.asarray(times, dtype=float)
    position_y_px = np.asarray(position_y_px, dtype=float)
    valid = np.isfinite(times) & np.isfinite(position_y_px) & (times >= 0)
    times = times[valid]
    position_y_px = position_y_px[valid]
    if times.size < 4 or np.unique(times).size < 3:
        return None

    try:
        fit_params, covariance = np.polyfit(times, position_y_px, 2, cov=True)
    except (ValueError, np.linalg.LinAlgError):
        return None
    acceleration_coefficient, velocity_px_per_s, _ = fit_params
    pixels_per_metre = -2.0 * acceleration_coefficient / constants.g
    if not np.all(np.isfinite(fit_params)) or pixels_per_metre <= 0:
        return None

    acceleration_variance = covariance[0, 0]
    pixels_per_metre_error = (
        2.0 * np.sqrt(acceleration_variance) / constants.g
        if np.isfinite(acceleration_variance)
        else np.nan
    )
    pixel_size = 1.0 / pixels_per_metre
    pixel_size_error = (
        pixels_per_metre_error / pixels_per_metre**2
        if np.isfinite(pixels_per_metre_error)
        else np.nan
    )

    return {
        "fit_params": fit_params,
        "pixel_size": pixel_size,
        "pixel_size_error": pixel_size_error,
        "initial_velocity": velocity_px_per_s / pixels_per_metre,
    }
