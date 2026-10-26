"""Software-only regression checks for the October cooling-code consolidation."""

import inspect

import numpy as np
import pytest

from artiq.coredevice.fastino import Fastino
from artiq.language.units import A, V, ms, s
from repository.fragments.mot import (
    BIASES_PGC,
    BIASES_CMOT,
    BIAS_CURRENT_STEP,
    FASTINO_VOLTAGE_LSB,
    CMOT_GRADIENT,
    DETUNING,
    DURATION,
    POWER_3D_MOT,
    SETTLE_TIME,
    MOT,
    Γ_Rb,
)
from repository.models.devices import VDrivenSupply
from repository.imaging.absorption_image import (
    pseudo_psd_objective,
    weak_cloud_od_threshold,
)


@pytest.mark.parametrize(
    ("atom_number", "sigma_x_mm", "sigma_y_mm"),
    [
        (2.0e8, 2.5, 2.5),
        (8.0e7, 1.1, 1.7),
        (1.4e8, 0.9, 0.8),
        (3.5e8, 3.1, 4.2),
    ],
)
def test_objective_preserves_previous_valid_fit_formula(
    atom_number, sigma_x_mm, sigma_y_mm
):
    previous = -np.log(atom_number / 2.0e8) + 2.0 * (
        np.log(sigma_x_mm / 2.5) + np.log(sigma_y_mm / 2.5)
    )
    assert pseudo_psd_objective(
        atom_number, sigma_x_mm, sigma_y_mm, 0.95
    ) == pytest.approx(previous, abs=1e-14)


@pytest.mark.parametrize(
    ("atom_number", "sigma_x_mm", "sigma_y_mm", "r_squared"),
    [
        (0, 2.5, 2.5, 0.95),
        (-1, 2.5, 2.5, 0.95),
        (np.nan, 2.5, 2.5, 0.95),
        (np.inf, 2.5, 2.5, 0.95),
        (2e8, 0.0, 2.5, 0.95),
        (2e8, -1.0, 2.5, 0.95),
        (2e8, np.nan, 2.5, 0.95),
        (2e8, 2.5, np.inf, 0.95),
        (2e8, 2.5, 2.5, 0.89),
        (2e8, 2.5, 2.5, np.nan),
    ],
)
def test_objective_penalises_invalid_images(
    atom_number, sigma_x_mm, sigma_y_mm, r_squared
):
    assert pseudo_psd_objective(atom_number, sigma_x_mm, sigma_y_mm, r_squared) == 5.0


@pytest.mark.parametrize(
    ("odt_active", "expected"),
    [(False, 0.1), (True, 0.01)],
)
def test_od_threshold_depends_on_boolean_parameter_value(odt_active, expected):
    assert weak_cloud_od_threshold(odt_active) == expected


def test_c1_cooling_defaults():
    assert DURATION["LOADING"] == 5.0 * s
    assert DURATION["CMOT"] == 4.0 * ms
    assert DURATION["PGC"] == 8.0 * ms
    assert SETTLE_TIME["CMOT"] == 3.79 * ms
    assert SETTLE_TIME["PGC"] == 0.5 * ms
    assert CMOT_GRADIENT["X"] == 0.6 * A
    assert DETUNING["PGC"] == 19 * Γ_Rb
    assert POWER_3D_MOT["PGC"] == 1.2 * V
    assert BIASES_PGC["X_Bias"] == 0.30e-3 * A


@pytest.mark.parametrize(
    ("axis", "amperes_per_volt"),
    [("X_Bias", 2.0), ("Y_Bias", 0.5), ("Z_Bias", 2.0)],
)
def test_bias_steps_match_fastino_dac_and_driver_gain(axis, amperes_per_volt):
    # ARTiq Fastino.voltage_to_mu() encodes 10 V as 0x8000 codes.
    assert FASTINO_VOLTAGE_LSB == pytest.approx(10.0 / 0x8000)
    assert BIAS_CURRENT_STEP[axis] == pytest.approx((10.0 / 0x8000) * amperes_per_volt)


def test_nominal_pgc_shims_are_quantised_by_fastino():
    def fastino_code(current, axis):
        return (
            int(Fastino.voltage_to_mu(None, current / VDrivenSupply[axis].gain))
            - 0x8000
        )

    # Nominal 0.30 mA in X is less than half of one 0.610 mA DAC step.
    assert fastino_code(BIASES_PGC["X_Bias"], "X_Bias") == 0
    assert fastino_code(BIASES_CMOT["X_Bias"], "X_Bias") == 1
    assert fastino_code(BIASES_PGC["Y_Bias"], "Y_Bias") == 2
    assert fastino_code(BIASES_PGC["Z_Bias"], "Z_Bias") == 98


def test_compress_contract_matches_all_callers():
    # Several trap-frequency experiments already call compress with two flags.
    assert list(inspect.signature(MOT.compress).parameters) == [
        "self",
        "evaporation_active",
        "odt_active",
    ]


def test_eom_sideband_enable_and_disable_are_distinct():
    class FakeEom:
        def __init__(self):
            self.calls = []

        def enable(self):
            self.calls.append("enable")

        def disable(self):
            self.calls.append("disable")

    mot = object.__new__(MOT)
    mot.eom = FakeEom()
    # Invoke the Python implementation without executing an ARTIQ kernel.
    MOT.Enable_EOM.artiq_embedded.function(mot)
    MOT.Disable_EOM.artiq_embedded.function(mot)
    assert mot.eom.calls == ["enable", "disable"]
