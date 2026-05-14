import numpy as np

# References: Steck Notes 
# [1] https://steck.us/alkalidata/rubidium87numbers.1.6.pdf
# [2] Marinescu, M., Sadeghpour, H. R., & Dalgarno, A. (1994). 
#     Dynamic dipole polarizabilities of rubidium. Physical Review A, 49(6), 5103.
# [3] Bai, Jiandong, et al. "Magic wavelengths for the 6S-7P transition of cesium 
# atoms." Results in Physics 52 (2023): 106853.


# Formulas 
# angular frequency (in rad/s) :  ω = 2πf = 1/(2πτ)
# decay rate (in rad/s): Γ = 2π × Δν 
# wavenumber (in meters): 2π/λ 

# Constants as Global variables 
C = 2.99792458 * 1e8      # speed of light in m/s
HBAR = 1.0545718 * 1e-34  # reduced Planck's constant in J·s
K_B = 1.380649 * 1e-23    # Boltzmann constant in J/K
PI = np.pi                # π
g =  9.80665              # acceleration due to gravity 9.80665 m/s²
G = 6.67430 * 1e-11       # gravitational constant 6.67430 × 10^-11 m^3/ kg·s².
M = 5.9722 * 1e24         # mass of the Earth 5.9722×10^24 kg
T = 100 * 1e-9            # temperature of BEC = 100 nK         
e_0 = 8.854 * 1e-12       # vaccum premittivity (in F/m)
mu_0 = 1.2566370614 *1e-6 # permeability of free space (in H/m)

# Atomic properties
# Rubidium-87 physical and optical (D1 line) properties 
m_Rb = 1.44316060 * 1e-25                     # mass of Rubidium-87 atom in kg 
alpha_Rb = 1.173 * 1e-38                      # ground state (5S₁/₂) dynamic scalar polarizability (in C m^2/V) 
                                              # with Nd:YAG laser at 1064 nm wavelengths.Theoretical value: 711.4 a.u. See Ref[2]
lambda_D1_Rb = 794.9788509 * 1e-9             # D1 transition (5^2S_1/2 ground state --> 5^2P1/2 excited state)
omega_0_D1_Rb = 2 * PI * 377.1074635*1e12     # angular frequency of Rb D2 line, ω_0 ≈ 2.106 x 10^15 rad/s
nat_lw_D1_Rb = 5.746*1e6                      # natural linewidth (in Hz), Δν  ≈ 5.746 MHz
Gamma_D1_Rb = 2 * PI * nat_lw_D1_Rb           # decay rate, Γ ≈ 3.61 × 10^7 rad/s
k_D1_Rb =  (2 * PI)/ lambda_D1_Rb             # wavenumber (in m)
f_D1_Rb = 0.342014                            # oscillator strength 

# Rubidium-87 optical (D2 line) properties 
lambda_D2_Rb = 780.241209686 * 1e-9           # D2 transition (5^2S_1/2 ground state --> 5^2P3/2 excited state)
omega_0_D2_Rb = 2 * PI * 384.2304844685*1e12  # angular frequency of Rb D2 line, ω_0 ≈ 2.414 x 10^15 rad/s
nat_lw_D2_Rb = 6.065*1e6                      # natural linewidth (in Hz), Δν  ≈ 6.065 MHz
Gamma_D2_Rb = 2 * PI * nat_lw_D2_Rb           # decay rate, Γ ≈ 3.811 × 10^7 rad/s
k_D2_Rb =  (2 * PI)/ lambda_D2_Rb             # wavenumber (in m)
f_D2_Rb = 0.695615                            # oscillator strength


# Caesium-133 physical and optical (D1 line) properties 
m_Cs = 2.20694650 * 1e-25                     # mass of a Cesium atom in kg
alpha_Cs = 1.129 * 1e-38                      # ground state (6S₁/₂) dynamic scalar polarizability (in C m^2/V) 
                                              # with Nd:YAG laser at 1064 nm wavelengths.Theoretical value: 685 a.u.  See Ref 
lambda_D1_Cs = 894.59295986*1e-9              # D1 transition (6^2S_1/2 ground state --> 6^2P1/2 excitied state)
omega_0_D1_Cs = 2 * PI * 335.116048807*1e12   # angular frequency, ω_0 ≈ 2.106 x 10^15 rad/s
nat_lw_D1_Cs =  5.2227*1e6                    # natural linewidth, Δν  ≈ 5.22 MHz
Gamma_D1_Cs = 2 * PI * nat_lw_D1_Cs           # decay rate, Γ ≈ 2.8659 × 10^7 rad/s
k_D1_Cs =  (2 * PI)/ lambda_D1_Cs             # wavenumber (in m)
f_D1_Cs = 0.3448690                           # oscillator strength

# Caesium-133  optical (D2 line) properties 
lambda_D2_Cs = 852.34727582 * 1e-9           # D2 transition (6^2S_1/2 ground state --> 6^2P3/2 excitied state)
omega_0_D2_Cs = 2 * PI * 351.72571850        # angular frequency, ω_0 ≈ 2.414 × 10^15 rad/s
nat_lw_D2_Cs =  5.24*1e6                     # natural linewidth, Δν  ≈ 5.24 MHz
Gamma_D2_Cs = 2 * PI * nat_lw_D2_Cs          # decay rate, Γ ≈ 3.2815 × 10^7 rad/s
k_D2_Cs =  (2 * PI)/ lambda_D2_Cs            # wavenumber (in m)
f_D2_Cs = 0.716418                           # oscillator strength

# Organize into dictionaries 
def get_globals():
    '''Function to return the global variables as a dictionary'''
    return {
        'C': C,
        'HBAR': HBAR,
        'K_B': K_B,
        'PI': PI,
        'G': G, 
        'M': M,
        'g': g,
        'T' : T,
        'e_0' : e_0,
        'mu_0' : mu_0
    }

def get_atomic_prop():
    '''Function to return the atomic properties of Rb-87 and 
       Cs-133 as a dictionary'''
    return {
        'm_Rb': m_Rb,
        'alpha_Rb': alpha_Rb,
        'lambda_D1_Rb': lambda_D1_Rb,
        'omega_0_D1_Rb': omega_0_D1_Rb,
        'nat_lw_D1_Rb': nat_lw_D1_Rb,
        'Gamma_D1_Rb': Gamma_D1_Rb,
        'k_D1_Rb': k_D1_Rb,
        'f_D1_Rb': f_D1_Rb,

        'lambda_D2_Rb': lambda_D2_Rb,
        'omega_0_D2_Rb': omega_0_D2_Rb,
        'nat_lw_D2_Rb': nat_lw_D2_Rb,
        'Gamma_D2_Rb': Gamma_D2_Rb,
        'k_D2_Rb': k_D2_Rb,
        'f_D2_Rb': f_D2_Rb,

        'm_Cs': m_Cs,
        'alpha_Cs': alpha_Cs,
        'lambda_D1_Cs': lambda_D1_Cs,
        'omega_0_D1_Cs': omega_0_D1_Cs,
        'nat_lw_D1_Cs': nat_lw_D1_Cs,
        'Gamma_D1_Cs': Gamma_D1_Cs,
        'k_D1_Cs': k_D1_Cs,
        'f_D1_Cs': f_D1_Cs,

        'lambda_D2_Cs': lambda_D2_Cs,
        'omega_0_D2_Cs': omega_0_D2_Cs,
        'nat_lw_D2_Cs': nat_lw_D2_Cs,
        'Gamma_D2_Cs': Gamma_D2_Cs,
        'k_D2_Cs': k_D2_Cs,
        'f_D2_Cs': f_D2_Cs
    }

# ------------ Define the cooling stages and their corresponding parameters ------------ 
def get_cooling_stages():
    return {
        "mot": ["delta_MOT", "P_MOT", "I_MOT", "I_bias_MOT", "t_load_MOT"],
        "cmot": ["delta_CMOT", "P_CMOT", "I_CMOT", "I_bias_CMOT", "t_ramp_CMOT", "t_hold_CMOT"],
        "pgc": ["delta_PGC", "P_PGC", "I_bias_PGC", "t_ramp_PGC", "t_hold_PGC"],
        "cdt": ["P1_init_CDT", "P2_init_CDT", "P1_final_CDT", "P2_final_CDT", 
                "delay", "t_cool_ramp_down", "t_coil_ramp_down", 
            "t_ODT_ramp_up", "t_evap"]
}

# ------------ Define the parameter bounds ------------
# Create dictionary for parameter bounds where
# each row is [lower_bound, upper_bound] for one parameter

def get_param_bounds():
    return {
    # MOT
    "delta_MOT"  : [ 1.0,  3.0],                    # detuning (Γ) | (1 - 3 Γ)
    "P_MOT"      : [ 60*1E-3,  90*1E-3],            # power (W) | (70 - 90 mW)
    "I_MOT"      : [ 0.5,  2.0],                    # anti-Helmholtz coil current (A) | (0.5 - 2 A)
    "t_load_MOT" : [ 5.0,  15.0],                   # load time (s) | (5 - 15 s)

    # CMOT
    "delta_CMOT"  : [3.0, 6.0],                     # detuning (Γ) | (3 - 6 Γ)
    "delta_repump_CMOT"  : [1.0, 3.0],              # repump detuning (Γ) | (1 - 3 Γ)
    "P_repump_CMOT"      : [ 1E-3,  5*1E-3],        # repump power (W) | (1 - 5 mW)
    "I_CMOT"      : [ 1.0,  3.0],                   # anti-Helmholtz coil current (A) | (1 - 3 A)
    "t_ramp_CMOT" : [ 1.0*1E-3, 30.0*1E-3],         # ramp time | (1 - 30 ms) 
    "t_hold_CMOT" : [ 0, 5.0*1E-3],                 # hold time (s) | (0 - 5 ms)

    # PGC
    "delta_PGC"  : [ 6.0, 11.0],                    # detuning (Γ) | (6 - 11 Γ)
    "I_bias_x_PGC" : [ 0.0,  0.2],                  # x-bias current (A) | (0 - 0.2 A)
    "I_bias_y_PGC" : [ 0.0,  0.2],                  # y-bias current (A) | (0 - 0.2 A)
    "I_bias_z_PGC" : [ 0.0,  0.2],                  # z-bias current (A) | (0 - 0.2 A)  NB: shimmers Earths B-field
    "t_ramp_PGC" : [ 15*1E-3, 40*1E-3],             # ramp time | (15 - 40 ms)
    "t_hold_PGC" : [ 0.0, 4.0*1E-3],                # hold time | (0 - 4 ms)
    
    # CDT
    "P1_init_CDT"       : [  10.0, 20.0],           # Initial CDT power beam 1 (W) | (10 - 20 W)
    "P2_init_CDT"       : [  1.0, 4.0],             # Initial CDT power beam 2 (W) | (1 - 4 W)
    "P1_final_CDT"      : [  1E-3, 100*1E-3],       # Final CDT power beam 1 (W) | (1 - 100 mW)
    "P2_final_CDT"      : [  1E-3, 100*1E-3],       # Final CDT power beam 2 (W) | (1 - 100 mW)
    "delay_1"           : [  1E-3, 10.0*1E-3],      # delay between cooling laser ramp and ODT (s) | (1 - 10.0ms)
    "delay_2"           : [  0.0, 5.0*1E-3],        # delay between coil ramp and ODT ramp(s) | (0.0 - 5.0 ms)
    "t_cool_ramp_down"  : [  1E-3, 10.0*1E-3],      # cooling laser ramp down time (s) | (1 - 10.0 ms)
    "t_coil_ramp_down"  : [  0.5*1E-3, 10.0*1E-3],  # coil ramp down time (s) | (0.5 - 10.0 ms)
    "t_ODT_ramp_up"     : [  1E-3, 100.0*1E-3],     # ODT ramp up (s) | (1 - 100.0 ms)
    "t_evap"            : [  1.0, 10.0]             # evaporation ramp duration (s) | (1 - 10 s)

}
