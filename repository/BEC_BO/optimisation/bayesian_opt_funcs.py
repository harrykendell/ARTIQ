# This script implements a black-box Bayesian optimization algorithm for optimizing an unknown function.
# The unknown function here represents the 4 stage cooling sequence to reach BEC (i.e., MOT, CMOT, PGC, CDT)
import torch
import numpy as np
import matplotlib.pyplot as plt

# import BoTorch functions
from botorch.models import SingleTaskGP
from botorch.fit import fit_gpytorch_mll
from gpytorch.mlls import ExactMarginalLogLikelihood
from gpytorch.kernels import MaternKernel, ScaleKernel
from botorch.acquisition.monte_carlo import (
    qExpectedImprovement,
    qUpperConfidenceBound,
    qProbabilityOfImprovement
    )
from botorch.acquisition.analytic import LogExpectedImprovement
from botorch.optim import optimize_acqf


from src.utils.get_results import get_measurement
from src.globals import get_cooling_stages,  get_param_bounds
from src.utils import make_tensors
from src.utils.param_selection import select_active_bounds, select_active_params
from src.utils.normalization import denormalize
from src.utils.param_selection import make_param_dict

cooling_stages = get_cooling_stages()
param_bounds = get_param_bounds()
param_names = list(param_bounds.keys())


def get_kernel(init_x, nu=2.5):
    """ Function to define a Matern kernel, defined 
    within a ScaleKernel wrapper.

    Inputs : 
        - init_x : (torch tensor) initial input training data
        - nu : 
    Outputs: 
        - covar_module : learned output variance
    """
    matern_kernel = MaternKernel(
                                nu=nu,
                                ard_num_dims=init_x.shape[-1]
    )

    # obtain output variance
    covar_module = ScaleKernel(matern_kernel)
    return covar_module

def build_surrogate_model(init_x, init_y, init_y_var):
    """Function to build the surrogate model (Heteroscedastic GP regressor) 
        for the BO loop. Fits a second GP to model how noise varies with x
    
    Inputs : 
        - init_x : (tensor) initial input training data
        - init_y : (tensor) initial output training data
        - init_y_var : (tensor) variance of the initial output
    
    Outputs :
        - model : the surrogate model (GP) fitted to the initial data
        - mll : the marginal log likelihood of the fitted model
    """
    # obtain Matern Kernel 
    covar_module = get_kernel(init_x, nu=2.5, )

    # create GP surrogate
    model = SingleTaskGP(
        train_X    = init_x,
        train_Y    = init_y,
        train_Yvar = init_y_var,
        covar_module=covar_module,
    )

    # define the marginal log likelihood 
    mll = ExactMarginalLogLikelihood(model.likelihood, model)
    return model, mll

def get_acquisition_function(model, best_init_y, acq_func_type):
    """Function to create the acquisition function (AF) for the BO loop.
    Allows user to select from different AF's (EI, logEI, UCB, PI).
    
    Inputs: 
        - model : the surrogate model (GP) fitted to the initial data
        - best_init_y : the best value of the target function
        - acq_func_type : the type of acquisition function (EI, logEI, UCB, PI)

    Outputs:
        - acq_func : the acquisition function
    """
    # initialize class for the different AF's
    if acq_func_type == "EI":
        acq_func = qExpectedImprovement(model=model, best_f=best_init_y)
    elif acq_func_type == "logEI":
        acq_func = LogExpectedImprovement(model=model, best_f=best_init_y)
    elif acq_func_type == "UCB":
        acq_func = qUpperConfidenceBound(model=model, beta=0.05)
    elif acq_func_type == "PI":
        acq_func = qProbabilityOfImprovement(model=model, best_f=best_init_y)
    else:
        raise ValueError("Invalid acquisition function type")
    return acq_func

def get_next_points(
        init_x, init_y, init_y_var, best_init_y, 
        bounds, n_points, acq_func_type):
    """
    This function is used to get the next point(s) to sample in the BO loop. 
    It does the following: 
        - Builds and trains the surrogate model (GP)
        - Creates the Acquistion Function (AF)
        - Find candidates for the next point to sample by optimizing the AF.
    
    Inputs :
        - init_x : (tensor) initial input training data
        - init_y : (tensor) initial output training data
        - init_y_var : (tensor) variance of the initial output
        - best_init_y : the best value of the target function
        - bounds : the bounds of the input domain
        - n_points : the no. of candidates to be found
        - acq_func_type : the type of AF (EI, UCB, PI)

    Outputs :
        - candidates: candidate(s) found while using a given AF
       -  model : the surrogate model (GP) fitted to the data
    """
    # create the GP models
    model, mll = build_surrogate_model(init_x, init_y, init_y_var)

    # fit the model for hyperparameter optimization
    fit_gpytorch_mll(mll) 

    # create the acquisition function
    acq_func = get_acquisition_function(model, best_init_y, acq_func_type)

    # find candidates
    candidates, _ = optimize_acqf(
        acq_function=acq_func,
        bounds=bounds,
        q=n_points,
        num_restarts=200,
        raw_samples=1024,
        options={"batch_limit": 5, "maxiter": 200},
    )

    return candidates, model

# Extract posterior mean and variance 
def get_posterior(model, test_X): 
    """Finds the posterior distribution at the 
    test points.
    
    Inputs : 
        - model : the trained GP model
        - test_X : (tensor) uniform grid across the parameter range
        Points to predict at. 
        
    Outputs: 
        - post_mean : (tensor) posterior mean
        - post_variance : (tensor) posterior variance
        - post_std : (tensor) posterior standard deviation
    """

    # switch the model to evaluation mode 
    model.eval()
    
    # compute μ, σ^2, and σ
    with torch.no_grad():
        posterior = model.posterior(test_X)
        post_mean      = posterior.mean            # μ
        post_variance  = posterior.variance        # σ^2
        post_std       = post_variance.sqrt()      # σ

    return post_mean, post_variance, post_std

def compute_confidence_interval(mean, std, z):
    """
    Computes confidence interval bounds (lower, upper).

    Inputs: 
        - mean, std : (tensors) mean and standard deviation 
        - z : (float) z-score | 1.96 for 95%, 2.576 for 99%, 1.0 for 68%

    Outputs: 
        - lower, upper : (tensors) lower and upper confidence bounds 
    """
    # compute bounds = μ +/- σ
    lower = mean - z * std
    upper = mean + z * std

    return lower, upper


def BO_function(
                init_x, init_y, init_y_var, best_init_y,
                phys_bounds, unit_bounds, n_points, 
                acq_func_type, n_init, m_samples, 
                iter_idx, active_params, artiq, session_name):

    """Used within the BO loop to update the training data with the candidate
    points found.

    Inputs :
        - init_x : (tensor) initial input training data
        - init_y : (tensor) initial output training data
        - init_y_var : (tensor) variance of the initial output
        - best_init_y : the best value of the target function
        - phys_bounds : the physical bounds of the input domain
        - unit_bounds : the unit bounds of the input domain
        - n_points : the no. of candidates to be found
        - acq_func_type : the type of AF (EI, UCB, PI)
        - n_init : number of initial samples
        - m_samples : the number of measurements to be taken per sample
        - iter_idx : iteration index in the BO loop
        - active_params : list of active parameter name
        - artiq : Artiq interface
        - session_name : session name 
        

    Outputs:
        - init_x : updated input training data
        - init_y : updated output training data
        - best_init_y : current best value of the target function
    """

    # get the next points that maximize the AF
    new_candidates, model = get_next_points(
        init_x, init_y, init_y_var, best_init_y, unit_bounds,
        n_points=n_points, acq_func_type=acq_func_type)

    # convert the new candidates for experimental use
    x = denormalize(new_candidates, phys_bounds)
    
    # make parameter dictionary 
    x_dict = make_param_dict(x, active_params)
    
    # define the sample index 
    n = n_init + iter_idx
    
    # run the experiment on Artiq
    raw_shots = artiq.run_bo_iteration(
            param_vector = x_dict,
            row_idx      = n,
            m_samples    = m_samples,
            session_name = session_name,
        )
    # collect new measurements 
    y, std_y = get_measurement(m_samples, raw_shots)
    
    # convert to tensors for GP fitting
    _, new_y, new_y_var = make_tensors(x, y, std_y)

    # append the data set with the new point(s)
    init_x = torch.cat((init_x, new_candidates))                                # update x-values
    init_y = torch.cat((init_y, torch.tensor(new_y).reshape(1,1)))              # update y-values
    init_y_var = torch.cat((init_y_var, torch.tensor(new_y_var).reshape(1,1)))  # update y-variances
    
    # obtain the best point so far
    best_init_y = init_y.max().item()

    return init_x, init_y, best_init_y, model

 
def plot_performance(init_y, best_init_y):
    """Plots the model performance /convergence
    for the all the measurements taken so far.
    
    Inputs : 
        - model : the trained GP model
        - init_y : the initial output training data
        - best_init_y : the best value of the target function
    
    Outputs: 
        - perc_imp : the % improvement from initial value 
    """
    # create list of iterations so far 
    iterations = np.arange(1, len(init_y) + 1)

    # convert from tensors to numpy 
    best_y = best_init_y.detach().cpu().numpy().flatten()

    # track best values 
    best_y_vals = np.accumulate(best_y)

    # create array for initial best
    init_best_y = best_y_vals[0] * np.ones(len(best_y_vals))
    
    # get % improvement from initial best
    perc_imp = ((best_y_vals - init_best_y) / init_best_y) * 100

    
    plt.step(iterations,perc_imp, where='post', color='maroon', label= 'Current best' )
    # add stating point
    plt.axhline(y=best_y_vals[0], color='red', linestyle='--', linewidth=2, label=f'Initial best = {best_y_vals[0]} %')
    plt.text(iterations.max() + 0.1, best_y_vals[0], f'{best_y_vals[0]}', color='red', va='center')
    plt.ylabel("% Improvement")
    plt.xlabel('BO iteration')
    plt.title("Model Performance", fontsize=13)
    plt.legend()
    plt.show()

    return perc_imp

    


def create_test_X( init_x, init_y, n_test, param_idx, fixed_values=None): 
    """Creates the (tensor) uniform grid across the parameter range 
    
    Inputs: 
        - selected_stages : active stages that are being optimized 
        - init_x : (tensor) the initial input training data
        - init_y : (tensor) the initial output training data
        - fixed_values : 
        - n_test : (integer) number of test points
        - param_idx      : (integer) parameter to vary along the slice

    Outputs: 
        - test_X : input matrix passed to get the posterior
        - test_vals : grid around chosen parameter
    """
    if fixed_values is None:
        # find the best point (parameter set) so far 
        best_idx = torch.argmax(init_y)
        # use this point as the baseline 
        fixed = init_x[best_idx].clone().unsqueeze(0)  # (1, d)
    else: 
        fixed = fixed_values.to(torch.float64)

    # create normalized sweep
    # Build test grid along the chosen parameter
    test_vals = torch.linspace(
        0, 1, n_test,
        dtype=torch.float64
    )

     # build the (n_test,d) input tensor
    test_X = fixed.unsqueeze(0).repeat(n_test, 1).clone()
    test_X[:, param_idx] = test_vals  
    return test_X, test_vals

def plot_gp_slice(model, init_x, init_y, init_y_var,
                  param_idx, param_name,
                  output_idx, output_name,
                  n_test, z):
    """
    Plot GP posterior mean and confidence interval along a 1D slice
    through parameter space, fixing all other parameters at their
    midpoint (or at fixed_values if provided).

    Inputs: 
        - model          : fitted GP
        - init_x : the initial input training data
        - init_y : the initial output training data
        - init_y_var : the variance of the initial output training data
        - param_idx      : int — which parameter to vary along the slice
        - param_name     : str — name of that parameter (for axis label)
        - output_idx     : int — which output to plot (0=N, 1=T)
        - output_name    : str — name of that output
        - n_test         : int — number of test points along the slice
        - z              : float — confidence interval z-score
        - fixed_values   : Tensor (d,) or None — fixed values for all parameters.
                        If None, uses midpoint of training data.
    """
    
    # get slice through the parameter space
    test_X, test_vals = create_test_X( init_x, init_y, n_test, param_idx, fixed_values=None)

    # Query posterior
    mean, variance, std = get_posterior(model, test_X)

    # Extract output of interest
    mean_1d  = mean[:, output_idx].numpy()
    std_1d   = std[:, output_idx].numpy()
    lower_1d = mean_1d - z * std_1d
    upper_1d = mean_1d + z * std_1d
    x_1d     = test_vals.numpy()

    # Extract training points projected onto this slice
    train_x_proj = init_x[:, param_idx].numpy()
    train_y_proj = init_y[:, output_idx].numpy()
    train_e_proj = init_y_var[:, output_idx].sqrt().numpy()  # SEM

    # ── Plot ──────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5))

    # Confidence interval shading
    ci_pct = int(round((1 - 2 * (1 - torch.distributions.Normal(0,1)
                                  .cdf(torch.tensor(z)).item())) * 100))

    ax.fill_between(x_1d, lower_1d, upper_1d,
                    alpha=0.25, color="#2f6bbf",
                    label=f"{ci_pct}% confidence interval")

    # Posterior mean
    ax.plot(x_1d, mean_1d, color="#2f6bbf", lw=2.0,
            label="Posterior mean")

    # Training observations with error bars
    ax.errorbar(train_x_proj, train_y_proj,
                yerr=1.96 * train_e_proj,
                fmt="o", color="#e05c2a", ms=5, lw=1.2,
                capsize=3, zorder=5,
                label="Training observations (±1.96 SEM)")

    ax.set_xlabel(param_name, fontsize=12)
    ax.set_ylabel(output_name, fontsize=12)
    ax.set_title(f"GP Posterior : {output_name} vs {param_name}", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    return fig, ax
