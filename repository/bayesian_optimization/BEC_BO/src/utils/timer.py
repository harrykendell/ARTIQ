## Construct an exact analog of the Matlab tic() and toc() functions. 

import time

def TicTocGenerator():
    # Generator that returns time differences
    ti = 0           # initial time
    tf = time.time() # final time
    while True:
        ti = tf
        tf = time.time()
        yield tf-ti # returns the time difference
#Initialize the generator
#TicToc = TicTocGenerator() # create an instance of the TicTocGen generator

# Main function for tic and toc functionality
def tic_toc(action="toc", print_time=True):
    global TicToc

    if action == "tic":
        # Reset the generator to start timing
        TicToc = TicTocGenerator()
        # Advance the generator to start timing
        next(TicToc)
        
    elif action == "toc":
        # Retrieve the elapsed time
        elapsed_time = next(TicToc)
        if print_time:
            print(f"Elapsed time: {elapsed_time:.6f} seconds")
        return elapsed_time