import numpy as np

from src.globals import get_cooling_stages,  get_param_bounds
from src.utils.normalization import denormalize

cooling_stages = get_cooling_stages()   # cooling stages & their parameters
param_bounds = get_param_bounds()       # parameter upper & lower bounds
param_names = list(param_bounds.keys()) # parameter names

def get_measurement( m_samples, raw_shots):
    """Function computes the statistics for an experiment run
    that uses the parameters in the sample `row_idx`.
    
    Inputs : 
        - m_samples : (integer) number of measurements per sample
        - raw_shots : (dict)  the raw shots 
    
    Outputs :
        - measurements_mean : (array) mean measurements of (N, σ_x, σ_y)
        - measurements_std : (array) standard error of the mean of (N, σ_x, σ_y)
    """
    # create measurement row matrix by stacking (N, σ_x, σ_y) 

    measurement_row = np.column_stack(
        (raw_shots["N"]),   # atom number from absorption image
        raw_shots["sx"],    # 1/e radii in x-direction 
        raw_shots["sy"] )   # 1/e radii in y-direction
    
    # calculate the mean and standard error for each parameter
    measurements_mean = np.mean(measurement_row, axis=0)
    measurements_std = np.std(measurement_row, axis=0) / np.sqrt(m_samples)

    return measurements_mean, measurements_std


def get_final_params(init_x, init_y, best_init_y, session_config):
    """Retrieves the best parameters found at the end of the BO.
    
    Inputs: 
        - init_x : (tensor) updated input training data
        - init_y : (tensor) updated output training data
        - best_init_y : (tensor) current best value of the target function
        - session_config :(dictionary) initial session configuration
    
    Outputs: 
        - final_config : (dictionary) final session configuration
    """

    # Retrieve the session information
    selected_stages =  session_config['selected_stages'] 
    active_params = session_config['active_params'] 
    phys_bounds = session_config['phys_bounds']  

    # find where the best values occurred 
    best_idx = np.where(init_y == best_init_y) 

    # get model parameters at this index
    best_x_norm = init_x[best_idx]

    # convert parameters back to physical units 
    best_x = denormalize(best_x_norm, phys_bounds)

    # Save final config dictionary as a JSON file
    final_results = {}
    val_idx = 0 

    for stage in selected_stages:
        # initialize stage in results dict
        final_results[stage] = {}
        # get this stages parameters 
        for param_name in active_params:
            val = best_x[val_idx]
            final_results[stage][param_name] = val
            val_idx += 1 
            
    return final_results



 