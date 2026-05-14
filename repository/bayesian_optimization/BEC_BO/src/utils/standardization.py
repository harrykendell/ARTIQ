def standardize(f, std_f):
    """Performs Z-score scaling to standardize 
    the function value and its uncertainty.
    Inputs: 
        - f : function values 
        - std_f : uncertainty/standard error of function

    Outputs: 
        - f_sc : scaled function values 
        - std_f_sc : scaled uncertainty
    """
    # get the mean and standard deviation of f
    f_mean = f.mean()
    f_std_dev = f.std()

    # scale the function value 
    f_sc = (f - f_mean) / f_std_dev

    # scale the uncertainty 
    std_f_sc = std_f / f_std_dev

    return f_sc, std_f_sc 