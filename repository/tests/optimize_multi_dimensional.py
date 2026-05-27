"""
Minimal optimisation example for ndscan with six parameters.

This is a small testbed for optimizers that need to handle changing numbers of
dimensions. Each subsequent variable adds a sharper or more corrugated
structure, and the later axes are deliberately coupled so the objective cannot
be minimized as independent one-dimensional scans. The noiseless global minimum
is exactly zero at the origin.
"""

from time import sleep

import numpy as np

from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    make_fragment_scan_exp,
)


class MultiDimensionalOptimisationSim(ExpFragment):
    def build_fragment(self):
        self.setattr_param(
            "delay",
            FloatParam,
            description="Artificial measurement delay",
            default=0.05,
            min=0.0,
            max=1.0,
            step=0.01,
            unit="s",
        )
        self.setattr_param(
            "x",
            FloatParam,
            description="Low-complexity quadratic anchor at zero",
            default=4.0,
            min=-5.0,
            max=5.0,
            step=0.1,
            unit="A",
        )
        self.setattr_param(
            "y",
            FloatParam,
            description="Quadratic residual coupled weakly to x",
            default=-4.0,
            min=-5.0,
            max=5.0,
            step=0.1,
            unit="A",
        )
        self.setattr_param(
            "z",
            FloatParam,
            description="Coupled residual with mild corrugation",
            default=2.5,
            min=-5.0,
            max=5.0,
            step=0.1,
            unit="Hz",
        )
        self.setattr_param(
            "u",
            FloatParam,
            description="Curved z/u valley with quartic walls",
            default=-3.0,
            min=-5.0,
            max=5.0,
            step=0.1,
            unit="V",
        )
        self.setattr_param(
            "v",
            FloatParam,
            description="Higher-frequency residual coupled to u and z",
            default=3.5,
            min=-5.0,
            max=5.0,
            step=0.1,
            unit="kHz",
        )
        self.setattr_param(
            "w",
            FloatParam,
            description="Strongly corrugated residual coupled to z, u, and v",
            default=-2.0,
            min=-5.0,
            max=5.0,
            step=0.1,
        )
        self.setattr_param(
            "noise_amplitude",
            FloatParam,
            description="Scales the noise term",
            default=0.0,
            min=0.0,
            max=1.0,
            step=0.001,
        )
        self.setattr_param(
            "noise_enabled",
            BoolParam,
            description="Add random noise to the objective",
            default=False,
        )
        self.setattr_result("objective", FloatChannel)

    def run_once(self):
        sleep(self.delay.get())  # Simulate some time-consuming measurement

        x = self.x.get()
        y = self.y.get()
        z = self.z.get()
        u = self.u.get()
        v = self.v.get()
        w = self.w.get()
        noise_amplitude = self.noise_amplitude.get()

        xy = y - 0.25 * x
        zxy = z + 0.18 * x * y - 0.12 * np.sin(13 * x)
        uzy = u - 0.30 * zxy**2 + 0.08 * y * z
        vuz = v + 0.35 * np.sin(17 * u) - 0.10 * z - 0.04 * x * y
        wvzu = w - 0.22 * np.sin(15 * v) + 0.16 * u * z - 0.05 * y**2

        objective = (
            0.35 * x**2
            + 0.70 * xy**2
            + 0.45 * zxy**2
            + 0.020 * (1.0 - np.cos(24 * z + 7 * x - 4 * y))
            + 0.34 * uzy**2
            + 0.030 * uzy**4
            + 0.018 * (1.0 - np.cos(32 * u + 11 * z - 5 * y))
            + 0.24 * vuz**2
            + 0.020 * (1.0 - np.cos(50 * v + 16 * u - 8 * z))
            + 0.012 * (1.0 - np.cos(30 * v * z))
            + 0.18 * wvzu**2
            + 0.018 * wvzu**4
            + 0.030 * (1.0 - np.cos(70 * w + 18 * v - 9 * u))
            + 0.018 * (1.0 - np.cos(25 * w * v))
            + 0.012 * (1.0 - np.cos(12 * w * z + 6 * u))
        )

        if self.noise_enabled.get():
            objective += noise_amplitude * np.random.normal()

        # NB: The minimum is exactly zero at the origin
        self.objective.push(objective)


MultiDimensionalOptimisationScan = make_fragment_scan_exp(
    MultiDimensionalOptimisationSim
)
