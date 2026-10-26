"""Regression checks for low-saturation atom-number formulae.

These tests exercise the actual AbsImage integration mask and cross-section,
without invoking the image fit (its fitted parameters are supplied explicitly).
"""

import math

import numpy as np
import pytest

from repository.imaging.processor import AbsImage, AbsImageSettings, gaussian_2D


@pytest.mark.parametrize("detuning_over_linewidth", [0.0, 0.25, 0.5, 1.0])
def test_gaussian_atom_number_matches_analytic_total(detuning_over_linewidth):
    wavelength = 780.24602089e-9
    linewidth = 6.065e6
    settings = AbsImageSettings(
        wavelength=wavelength,
        linewidth=linewidth,
        detuning=detuning_over_linewidth * linewidth,
        magnification=0.227,
    )
    height, width = 241, 241
    y, x = np.mgrid[:height, :width]
    parameters = {
        "A": 3.0,
        "x0": 115.0,
        "y0": 123.0,
        "sx": 21.0,
        "sy": 29.0,
        "theta": 0.35,
        "z0": 0.0,
    }
    od = gaussian_2D(x, y, **parameters)

    image = AbsImage.__new__(AbsImage)
    image.settings = settings
    image.width = width
    image.height = height
    image.data_image = np.zeros_like(od)
    # Reuse the production Gaussian mask, but remove unrelated acquisition/fitting steps.
    image.__dict__["best_values"] = parameters
    image.__dict__["beam_mask"] = np.ones_like(od, dtype=bool)
    image.__dict__["cloud_optical_density"] = od

    sigma_0 = 3 * wavelength**2 / (2 * math.pi)
    expected_cross_section = sigma_0 / (1 + 4 * detuning_over_linewidth**2)
    expected = (
        2 * math.pi * parameters["A"] * parameters["sx"] * parameters["sy"]
        * image.physical_scale**2 / expected_cross_section
    )
    # Finite pixels approximate the analytic continuous Gaussian integral.
    assert image.atom_number == pytest.approx(expected, rel=0.002)


def test_integration_ellipse_contains_expected_gaussian_fraction():
    settings = AbsImageSettings()
    y, x = np.mgrid[:241, :241]
    parameters = {
        "A": 1.0,
        "x0": 120.0,
        "y0": 120.0,
        "sx": 20.0,
        "sy": 27.0,
        "theta": 0.28,
        "z0": 0.0,
    }
    od = gaussian_2D(x, y, **parameters)
    image = AbsImage.__new__(AbsImage)
    image.settings = settings
    image.width = 241
    image.height = 241
    image.data_image = np.zeros_like(od)
    image.__dict__["best_values"] = parameters
    image.__dict__["beam_mask"] = np.ones_like(od, dtype=bool)
    fraction = od[image.sigma_mask].sum() / od.sum()
    assert fraction == pytest.approx(1 - math.exp(-4.343 / 2), abs=0.001)
