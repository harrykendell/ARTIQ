import numpy as np
import torch
from src.globals import get_cooling_stages,  get_param_bounds

cooling_stages = get_cooling_stages()   # cooling stages & their parameters
param_bounds = get_param_bounds()       # parameter upper & lower bounds
param_names = list(param_bounds.keys()) # parameter names

def select_active_params(selected_stages):
    """Function to get the active parameters based on the selected stages.
    Inputs: 
        - selected_stages : user-selected stages to be optimized
    Outputs: 
        - active_param_indices : (list) indicies for active parameters
        - active_params : (list) active parameter names 
    """
    
    # filter the stages based on user selection
    enabled_stages = [stage for stage, enabled in selected_stages.items() if enabled]
    active_params = []
    
    for stage in enabled_stages:
        active_params.extend(cooling_stages[stage])
    
    # obtain indicies for active parameters
    active_param_indices = [param_names.index(p) for p in active_params]
    
    return active_param_indices, active_params

def active_bounds_arrays(active_params, param_bounds):
    """Function to select the bounds of the input domain for the optimization.
       Keeps the bounds as numpy arrays.

    Inputs : 
        - active_params : (list) active parameter names
        - param_bounds : (dictionary) parameter bounds
    
    Outputs : 
        - active_bounds_lower : ((1,d') array) active lower bound
        - active_bounds_upper : ((1,d') array) active upper bound
    """
    # define the bounds for the active parameters 
    active_bounds_lower = np.array([param_bounds[p][0] for p in active_params])
    active_bounds_upper = np.array([param_bounds[p][1] for p in active_params])

    return active_bounds_lower, active_bounds_upper 

def select_active_bounds(active_params, param_bounds):
    """Function returns the bounds for active parameters as torch tensors.

    Inputs : 
        - active_params : list of active parameter names
        - param_bounds : dictionary of parameter bounds
    
    Outputs : 
        - bounds : ((2, d') tensor) bounds where d' =  no.of active parameters
    """
    # define the bounds for the active parameters 
    active_bounds_lower, active_bounds_upper = active_bounds_arrays(active_params, param_bounds)

    # convert to torch tensors for GP fitting
    lower = torch.tensor(active_bounds_lower, dtype=torch.double)
    upper = torch.tensor(active_bounds_upper, dtype=torch.double)

    bounds  = torch.stack((lower, upper))  # shape (2, num_active_params)
    return bounds 

def make_unit_bounds(active_params):
    """Function returns the unit bounds that will be used 
    in the unit hypercube optimization.
    
    Inputs : 
        - active_params : list of active parameter names
    
    Outputs: 
        - unit_bounds : ((2, d') tensor) unit bounds 
    """
    # get number of active parameters
    d = len(active_params)

    # create bounds
    unit_bounds = torch.stack([
        torch.zeros(d, dtype=torch.double),
        torch.ones(d,dtype=torch.double)
    ])
    return unit_bounds



def make_param_dict(parameters, active_params): 
    """Creates a parameter dictionary to be read
    by the actual experiment following optimization

    Inputs: 
        - parameters : ((1,d) array) vector with d input parameters 
        - active_params : list of active parameter names
    
    Outputs: 
        - param_dict : (dictionary) active parameters and their values
    """

    # create dictionary 
    param_dic = {}
    for param, x in zip(active_params, parameters):
        param_dic.update({param: x})

    return param_dic

def read_param_dict(param_dict): 
    """Reads the parameter dictionary for the current
    experimental run, extracts the values and passes 
    it to the experiment. Used within Artiq interface
    
    Inputs: 
        - param_dict : (dictionary) active parameters and their values
    
    Outputs:
        - param_names  : (list[str]) ordered parameter names
        - param_values : (np.ndarray) corresponding physical values
    """
    param_names  = list(param_dict.keys())
    param_values = np.array(list(param_dict.values()))

    return param_names, param_values

