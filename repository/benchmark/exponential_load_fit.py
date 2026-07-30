import numpy as np

from submodules.oitg.oitg.fitting import FitBase


def parameter_initialiser(x, y, p):

    p["y0"] = y[np.argmin(x)]
    p["x0"] = np.min(x)
    p["y_inf"] = np.max(y)
    p["tau"] = (np.max(x) - np.min(x)) / 5


def fitting_function(x, p):

    y = p["y0"] + (p["y_inf"] - p["y0"]) * (1 - np.exp(-(x - p["x0"]) / p["tau"]))

    # Hold constant before loading begins
    y = np.where(x <= p["x0"], p["y0"], y)

    return y


def derived_parameter_function(p, p_err):

    p["t_1_e"] = p["x0"] + p["tau"]

    p_err["t_1_e"] = np.sqrt(p_err["x0"] ** 2 + p_err["tau"] ** 2)

    return p, p_err


exponential_load = FitBase.FitBase(
    ["x0", "y0", "y_inf", "tau"],
    fitting_function,
    parameter_initialiser=parameter_initialiser,
    derived_parameter_function=derived_parameter_function,
    derived_parameter_names=["t_1_e"],
)
