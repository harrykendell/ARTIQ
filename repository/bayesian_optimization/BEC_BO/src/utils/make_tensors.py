import torch 

def make_tensors(x, y, y_std):
    """Function to convert the initial data to torch tensors for GP fitting.
    Inputs : 
        - x : (n, d) array of initial parameter vectors
        - y : (n,) array of initial target function values
        - y_std : (n,) array of standard deviation of the initial target function values
    Outputs :
        - init_x : (n, d) tensor of initial parameter vectors
        - init_y : (n, 1) tensor of initial target function values
        - init_y_var : (n, 1) tensor of variance of y
    """

    # convert to torch tensors 
    init_x = torch.from_numpy(x).double()
    init_y = torch.from_numpy(y).double().unsqueeze(-1)
    init_y_var = torch.from_numpy(y_std**2).double().unsqueeze(-1) # variance is std^2

    return init_x, init_y, init_y_var
