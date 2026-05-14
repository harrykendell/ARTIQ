# This scripts contains functions to calculate the values of certain parameters from 
# experimental inputs. 

# References : 
# [1] Anti-Helmholtz Coils : https://explerify.com/simulator-anti-helmholtz-coil/

from src.globals import get_globals

# get the global variables 
global_vars = get_globals()
mu_0 = global_vars['mu_0']

def get_B_field_gradient(coil_params, I_current): 
    """Function computes the magnetic field gradient (B') 
    produced by a pair of anti-Helmholtz coils.
    
    Inputs: 
        - coil_params : a dictionary for fixed coil parameters.
        - I_current : the current flowing through the coils (in Amperes).
    
    Outputs: 
        - B_gradient : the magnetic field gradient (in Tesla/meter).

    """

    # unpcack the coil parameters
    N_turns = coil_params['N_turns'] # number of turns in each coil
    R_coil = coil_params['R_coil'] # radius of each coil
    d_coil = coil_params['d_coil'] # distance between the two coils

    # compute dB/dz at the center along the axis (z-axis) [1]
    B_grad = (3 * mu_0 * N_turns * I_current * d_coil/2) * (R_coil**2) / (2 * ((R_coil**2 + (d_coil/2)**2)**(5/2))) 

    return B_grad