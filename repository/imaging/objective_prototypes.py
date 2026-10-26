# Dormant CMOT/PGC objective prototypes, preserved from ARTIQ main b342235.
#
# This file is intentionally comment-only. None of the following code runs or
# changes the published custom_objective channel. It is kept because the stage-
# specific benchmark references and in-situ-width/PSD approaches may be useful
# when calibrated TOF thermometry and F1/F2 imaging are available.
#
# Before using these: verify TOF units, nonzero release covariance, in-situ
# widths, state-dependent atom number, and physical probe-aperture truncation.
# The original sketches below were not independently validated.
#
# from scipy.constants import h as H_PLANCK, k as K_B
# M_RB = 1.443160648e-25  # kg, Rb-87
#
# fixed reference values during expansion (based on benchmarks)
# STAGE_REF = {
#     "cmot": {
#         "N": 3.0e8,
#         "x_mm": 2.0,
#         "y_mm": 2.0,
#     },
#     "pgc": {
#         "N": 2.0e8,
#         "x_mm": 2.5,
#         "y_mm": 2.5,
#     },
# }
#
# In situ fixed reference values
# STAGE_SITU_ = {
#     "cmot": {
#         "x_mm": 0.91,
#         "y_mm": 1.08,
#         "source": "parameter-scan thermometry, 2026-10-05",
#     },
#     "pgc": {
#         "x_mm": 0.91,
#         "y_mm": 1.07,
#         "source": "parameter-scan thermometry, 2026-10-06",
#     },
# }
#
#     # last enabled stage
#     if self.do_pgc.get():
#         stage = "pgc"
#     elif self.do_cmot.get():
#         stage = "cmot"
#     else:
#         raise ValueError(
#             "Neither CMOT nor PGC enabled: no PSD reference for this sequence"
#         )
#
# ---- Stage-specific candidate objective and thermometry sketches ----
# def pseudo_psd_objective(N, STAGE_REF, exponent, stage):
#     """
#     Returns the negated log(pseduo PSD) for a single shot.
#     """
#     # initial cloud widths (in-situ) in x-y directions
#     sx_ref = STAGE_REF[stage]["x_mm"]
#     sy_ref = STAGE_REF[stage]["y_mm"]
#
#     return -np.log(N / STAGE_REF[stage]["N"]) + exponent * (
#         np.log(sx_mm / sx_ref) + np.log(sy_mm / sy_ref)
#     )
#
# if fit_failed:
#     # Push a large value penalty
#     self.custom_objective.push(5)
# else:
#     self.custom_objective.push(pseudo_psd_objective(N, STAGE_REF, exponent, stage))
#
# Custom Objective 2 : negated log(estimate PSD)
#
# PSD_REF = 1e-7  # reference PSD
#
# def estimate_psd_objective(N, STAGE_SITU, sx_mm, sy_mm, stage):
#     """
#      Computes for a single shot,
#           - the objective value (J)
#           - the average temperature estimate (T_avr)
#           - the computed PSD (psd) for one shot,
#      Otherwise returns (PSD_PENALTY, None, None) if invalid.
#     """
#
#     # initial x-y (in-situ) cloud widths (in m)
#     s0x = STAGE_SITU[stage]["x_mm"] * 1e-3
#     s0y = STAGE_SITU[stage]["y_mm"] * 1e-3
#
#     # imaging TOF
#     t = self.expansion_time * 1e-3  # s
#
#     # compute x-y temperatures
#     T_x = (M_RB / K_B) * ((sx_mm * 1e-3) ** 2 - s0x**2) / t**2
#     T_y = (M_RB / K_B) * ((sy_mm * 1e-3) ** 2 - s0y**2) / t**2
#
#     if not (T_x > 0 and T_y > 0 and N > 0):
#         return PENALTY, None, None
#
#     # find average temperature
#     T_avr = 0.5 * (T_x + T_y)
#
#     # compute PSD
#     n = N / ((2 * np.pi) ** 1.5 * s0x**2 * s0y)  # peak density, σ_z = σ_x
#
#     lam = H_PLANCK / np.sqrt(
#         2 * np.pi * M_RB * K_B * T_avr
#     )  # thermal de Broglie wavelength
#
#     psd = n * lam**3
#
#     return -np.log(psd / PSD_REF), T_avr, psd
#
# if fit_failed:
#     self.custom_objective.push(PENALTY)
#
# else:
#     J, self.T_avr, self.psd = estimate_psd_objective(
#         N, STAGE_SITU, sx_mm, sy_mm, stage
#     )
#     self.custom_objective.push(J)
#
