import numpy as np
import pandas as pd
from src.globals import get_param_bounds
from scipy.stats.qmc import LatinHypercube, scale

param_bounds = get_param_bounds()

# To make this more general, we use LHS sampling on selected parameters. 
def LHS_sampler(n,active_param_indices, user_seed):
    """Function to generate initial parameters for BO using Latin Hypercube Sampling (LHS).
    Inputs: 
        - n : number of initial samples to generate
        - active_param_indices : list of indices of active parameters to sample
        - user_seed : random seed for reproducibility
    Outputs: 
        - X_init : (n, d) array of initial parameter vectors
    """

    # Define the parameter bounds 
    # create dictionary for parameter bounds where
    # each row is [lower_bound, upper_bound] for one parameter
   
    param_names = [list(param_bounds.keys())[i] for i in active_param_indices]
    lower_lhs = np.array([v[0] for v in param_bounds.values()])[active_param_indices]
    upper_lhs = np.array([v[1] for v in param_bounds.values()])[active_param_indices]

    d = len(param_names)   # size of parameter dimensions 

    #  generate LHS samples 
    if user_seed is not None:
        # set the random seed for reproducibility
        seed =user_seed
    sampler  = LatinHypercube(d=d, seed=seed) # LHS sampler with fixed seed (for reproducibility)
    unit_samples = sampler.random(n=n)        # shape (n, d), values in [0, 1]

    #  scale from [0,1] to the actual parameter ranges 
    init_params = scale(unit_samples, l_bounds=lower_lhs, u_bounds=upper_lhs)  # shape (n, d)

    #  inspect
    init_params_df = pd.DataFrame(init_params, columns=param_names) # DataFrame 
    print(init_params_df.round(3).to_string())
    print(f"\nShape: {init_params.shape}")   # (n,d)

    return init_params