from src.globals import get_cooling_stages,  get_param_bounds
from src.utils.param_selection import active_bounds_arrays

cooling_stages = get_cooling_stages()
param_bounds = get_param_bounds()
param_names = list(param_bounds.keys())

def normalize(x, active_params): 
    """Normalizes the input X to be between [0,1]
            x_norm = (x - lower) / (upper - lower) 
    
    Inputs: 
        - x : ((n,d) array) input parameters in physical units
        - active_params : list of active parameter names
    
    Outputs: 
        - normalized parameters
    """
    lower_active, upper_active = active_bounds_arrays(active_params, param_bounds)
    return (x - lower_active) / (upper_active - lower_active)

def denormalize(x_norm, phys_bounds): 
    """Converts the normalized parameters to physical values.
            x = x_norm * (upper - lower) + lower
    
    Inputs: 
        - x_norm: ((n,d) tensor)  input parameters between [0,1] 
        - phys_bounds : ((2,d) tensor) physical lower and upper bounds
    
    Outputs: 
        - x : (array) input parameters in physical units
    """
    # denormalize [0,1] to physical units 
    x_phy = x_norm * (phys_bounds[1] - phys_bounds[0]) + phys_bounds[0]

    # convert to numpy arrays 
    x = x_phy.detach().cpu().numpy().flatten()  

    # if hardware require float32, convert to float32
    # x = x_phy.detach().cpu().numpy().astype(np.float32)

    return x