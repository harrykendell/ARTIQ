import numpy as np
from pathlib import Path

from utils.param_selection import select_active_params
from optimisation.objective_funcs import objective_function
from src.globals import get_cooling_stages,  get_param_bounds
from utils.sampler import LHS_sampler
from src.utils.make_tensors import make_tensors
from src.utils.normalization import normalize
from src.utils.param_selection import make_param_dict
from utils.get_results import get_measurement


# get the global variables
cooling_stages = get_cooling_stages()
param_bounds = get_param_bounds()
param_names = list(param_bounds.keys())

# create path to save measurements 
save_path = Path() / "BO_runs"/"initial_data" 
save_path.mkdir(parents=True, exist_ok=True)

def generate_initial_data(n_init,m_samples, save_path, 
                          active_params, selected_stages, 
                          user_seed, artiq, session_name): 
    """
    Generates input and output tensors of size/length n. 
    These will be the training data for the model.

    Input:
        - n_init : number of initial samples to generate
        - m_samples : number of shots per experimental run
        - save_path : path to save the experimental results
        - active_params : list of active parameter names
        - selected_stages : list of stages being optimized
        - user_seed : random seed for reproducibility
        - artiq : Artiq interface
        - session_name : session name 
    
    Outputs :
        - x : un-normalized input data (for inspection)
        - init_x : input training data
        - init_y : output training data
        - init_y_var : variance of the output training data
        - best_init_y : maximum value of target function
    """
    # get the active parameters and their bounds based on user selection of stages
    active_param_indices, _ = select_active_params(selected_stages)

    # generate initial parameter input using LHS sampling
    x = LHS_sampler(n_init, active_param_indices, user_seed)

    # create arrays to store results
    all_measurements = np.zeros((n_init, 3))  # means of (N, σ_x, σ_y)
    all_stds = np.zeros((n_init, 3))          # standard errors

    # obtain y-values 
    for n in range(n_init):
        # make parameter dictionary 
        x_dict = make_param_dict(x[n,:], active_params)
        # run the experiment on Artiq
        raw_shots = artiq.run_bo_iteration(
                param_vector = x_dict,
                row_idx      = n,
                m_samples    = m_samples,
                session_name = session_name,
            )
        measurements_mean, measurements_std = get_measurement(m_samples, raw_shots[n])
        # collect all measurements 
        all_measurements[n,:] = measurements_mean
        all_stds[n,:] = measurements_std

    # evaluate the objective function for each row in the measurements and standard error arrays 
    y, std_y = np.array([objective_function(meas, std, selected_stages) for meas, std in zip(all_measurements, all_stds)]) 
    
    # normalize the x data to be between [0,1]
    x_norm = normalize(x, active_params)

    # convert to tensors for GP fitting
    init_x, init_y, init_y_var = make_tensors(x_norm, y, std_y )

    # get the best observed value of the target function
    best_init_y = init_y.max().item()

    return x, init_x, init_y, init_y_var, best_init_y


  # NB: I will figure out later how to run the experiment and collect measurements 
  # in a more efficient way  i.e., using a Class