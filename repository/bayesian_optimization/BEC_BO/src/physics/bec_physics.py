import numpy as np
from src.globals import get_globals, get_atomic_prop

# Accessing variables from global_vars and atomic properties
global_vars = get_globals()
atomic_props = get_atomic_prop()

PI = global_vars['PI']
h = global_vars['HBAR'] * 2 * PI
K_B = global_vars['K_B']

m_Rb = atomic_props['m_Rb']

def compute_sigma_z(sigma_x, sigma_y, std_sigma_x, std_sigma_y, selected_stages):

    """Function to compute the 1/e radius of the cloud in the z-direction.
    This assumes only 2 imaging axes (x and y) are available.
    Inputs: 
        - sigma_x, sigma_y : 1/e radii of the cloud in x and y directions
        - std_sigma_x, std_sigma_y : uncertainties in sigma_x and sigma_y
        - selected_stages : list of stages being optimized
    Outputs: 
        - sigma_z : 1/e radius of the cloud in z-direction
        - std_sigma_z : uncertainty in sigma_z 
    """

    # check if CDT is being optimized 
    if "CDT" in selected_stages:
        # if CDT is being optimized, σ_z = σ_y
        sigma_z = sigma_y
        std_sigma_z = std_sigma_y
    else: 
        # σ_z = σ_x for other stages
        sigma_z = sigma_x
        std_sigma_z = std_sigma_x
    return sigma_z, std_sigma_z

def get_number_density(measurement, measurement_std, selected_stages):
    """Function to compute the number density of the 
    trapped gas from the measurement results.
    Uses effective volume for thermal (Gaussian) cloud

    Inputs : 
        - measurement : vector of mean measurement results (N, σ_x, σ_y)
        - measurement_std : vector of statistical uncertainties of (N, σ_x, σ_y) 
        - selected_stages : list of stages being optimized

    Outputs : 
        - n_peak : peak number density (in cm^-3)
        - std_n_peak : uncertainty in n_peak
    """
    # unpack the measurement and standard deviation vectors
    N, sigma_x, sigma_y = measurement
    std_N, std_sigma_x, std_sigma_y = measurement_std

    # obtain sigma_z and its uncertainty 
    sigma_z, std_sigma_z = compute_sigma_z(sigma_x, sigma_y, std_sigma_x, std_sigma_y, selected_stages)

    # compute the  effective volume of the cloud 
    V_eff = ((2 * PI)**(3/2)) * (sigma_x * sigma_y * sigma_z)

    # find the number density
    n_peak = N / V_eff

    # compute uncertainty in n_peak using relative fractional uncertainties 
    std_n_peak = n_peak * np.sqrt( (std_N/N)**2 + (std_sigma_x/sigma_x)**2 + (std_sigma_y/sigma_y)**2 + (std_sigma_z/sigma_z)**2 )

    return n_peak, std_n_peak

def get_phase_space_density(n_peak,T):
    """Function to compute the phase space density (PSD) of a thermal gas.
    
    Inputs: 
        - n_peak : peak density (in cm^-3)
        - T : temperature (in Kelvin)
    
    Outputs: 
        - PSD : phase space density (dimensionless)

    """
    n_peak_m3 = n_peak * 1e6  # convert from cm^-3 to m^-3
    
    # compute the thermal de Broglie wavelength
    lambda_db = h / np.sqrt(2 * PI * m_Rb * K_B * T)  # in meters
    
    # compute the phase space density
    PSD = n_peak_m3 * (lambda_db**3) 

    return PSD