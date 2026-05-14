# Define the objective functions for the optimization 
import numpy as np
from src.physics.bec_physics import compute_sigma_z
from src.globals import get_globals, get_atomic_prop
from src.utils.standardization import standardize

# Accessing variables from global_vars and atomic properties
global_vars = get_globals()
atomic_props = get_atomic_prop()

PI = global_vars['PI']

def objective_function(measurement, measurement_std, selected_stages,  alpha=0.8):
    """ Defined the objective to be maximized as a weighted sum of two
        objectives : increase number density while keep atom number high.
    
    Inputs :
        - measurement: the vector of mean measurement results (N, σ_x, σ_y)
        - measurement_std: the vector of standard deviations of measurement results (N, σ_x, σ_y)
        - selected_stages: a list of stages being optimized
        - alpha: a weighting factor to balance the importance of N and PSD
    
    Outputs: 
        - f : scaled objective function value
        - std_f : scaled uncertainty in the objective function value
    """

    # unpack the measurement and standard deviation vectors
    N, s_x, s_y = measurement
    std_N, std_s_x, std_s_y = measurement_std

    # obtain sigma_z and its uncertainty 
    s_z, std_s_z = compute_sigma_z(s_x, s_y, std_s_x, std_s_y, selected_stages)

    # estimate the objective function
    f = (1 + alpha) * np.log10(N) - np.log10(s_x * s_y * s_z) - np.log10((2 * PI)**(3/2))

    # use error propagation of logs to estimate the objective function uncertainty
    std_f = (1/np.log(10)) * np.sqrt( ((1 + alpha)**2 * (std_N/N)**2) + (std_s_x/s_x)**2 + (std_s_y/s_y)**2 + (std_s_z/s_z)**2 )

    # scale the y values and its uncertainty 
    f_sc, std_f_sc = standardize(f, std_f)

    return f_sc, std_f_sc