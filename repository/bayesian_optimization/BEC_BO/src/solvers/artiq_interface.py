
import numpy as np
import json
import os
import time
from sipyco.pc_rpc import Client

from src.utils.param_selection import read_param_dict
from src.globals import get_cooling_stages,  get_param_bounds
from src.utils.param_selection import select_active_bounds, make_unit_bounds

cooling_stages = get_cooling_stages()   # cooling stages & their parameters
param_bounds = get_param_bounds()       # parameter upper & lower bounds
param_names = list(param_bounds.keys()) # parameter names


class BOARTIQInterface:
    """
    Interface between the BO loop and ARTIQ.

    Responsibilities:
        - Read session config written by BOConfigFrag
        - Submit BOExperimentFrag runs to the ARTIQ scheduler
        - Wait for completion
        - Read back (N, sx, sy) from ARTIQ datasets
    """

    def __init__(self, host="::1",
                 scheduler_port=3251,
                 dataset_port=3251):
        """
        Connect to the ARTIQ master.

        Inputs:
            - host           : (string)  ARTIQ master IP
            - scheduler_port : (integer)  scheduler RPC port
            - dataset_port   : (integer)  dataset manager RPC port
        """
        self.scheduler = Client(host, scheduler_port,  # for submitting, querring or cancelling jobs
                                 "master_schedule")  
        self.datasets  = Client(host, dataset_port,    # for storing and reading results 
                                "master_dataset_db") 

    # read the session configuration
    def read_session_config(self, file_path):
        """
        Reads the session configuration saved as an
        Artiq dataset before starting the BO loop.
        Inputs: 
            - file_path : (string) file path to saved session configuration
        Outputs: 
            config : dict with keys bo_config._:
                - session_name     : (string) session name
                - active_params    : (list[str]) active parameters
                - phys_bounds      : (Tensor (2, d)) physical bounds
                - unit_bounds      : (Tensor (2, d)) unit bounds
                - selected_stages  : (list[str]) selected stages to optimize
                - m_samples        : (integer) no.of shots per experimental run
                - n_init           : (integer) no.of initial samples 
                - n_iterations     : (integer) no.of iterations in BO loop
                
        """
    
        # Check if file exists
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Session config not found: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as file:
            datasets = json.load(file)  # Parse JSON into Python object

        # datasets has structure:
        # {
        #   "metadata":     {"session_name": ..., "date": ..., ...},
        #   "optimisation": {"active_params": [...], "n_init": ..., ...},
        #   "bounds":       {"delta_MOT": {"lower": ..., "upper": ...}, ...}
        # }
        
        active_params = datasets["optimisation"]["active_params"]
       
        # get active bounds (physical and unit)
        phys_bounds = select_active_bounds(active_params, param_bounds)
        unit_bounds = make_unit_bounds(active_params)
        
        # create dictionary 
        config = {
            "session_name"   : datasets["metadata"]["session_name"],
            "active_params"  : active_params,
            "selected_stages": datasets["optimisation"]["selected_stages"],
            "phys_bounds"    : phys_bounds,
            "unit_bounds"    : unit_bounds,
            "m_samples"      : datasets["optimisation"]["m_samples"],
            "n_init"         : datasets["optimisation"]["n_init"],
            "n_iterations"   : datasets["optimisation"]["n_iterations"],
        }

        # print session info
        print("Session config loaded:")
        print(f"Session Name          : {config['session_name']}")
        print(f"Selected Stages       : {config['selected_stages']}")
        print(f"No.of active params   : {len(active_params)}")
        print(f"Active Parameters     : {config['active_params']}")

        return config
    
    def tof_experiment(self, param_vector, row_idx, sample_idx,
                    m_samples, session_name,
                    pipeline="main", priority=1,
                    poll_interval=0.5, timeout=300):
        """
        Run one complete TOF absorption imaging shot via ARTIQ.
        This method that calls BOExperimentFrag once.

        Sequence:
            1. Submits BOExperimentFrag to ARTIQ scheduler
            2. Waits for completion (the actual experiment + save)
            3. Reads (N, sx, sy) from saved ARTIQ datasets

        Inputs:
            - param_vector  : (dictionary) input parameters
            - row_idx       : (integer) BO iteration index
            - sample_idx    : (integer) shot index within iteration (0 to m-1)
            - m_samples     : (integer) total shots per iteration
            - session_name  : (string)  BO session name
            - pipeline      : (string)  independent experiment queue on ARTIQ
            - priority      : (integer) scheduler priority
            - poll_interval : (float) time between status checks [s]
            - timeout       : (float) max wait time [s]

        Outputs:
            - N    : (float) atom number
            - sx_m : (float) 1/e radii in x-direction [m]
            - sy_m : (float) 1/e radii in y-direction [m]
        """

        # step 1-2: submit BOExperimentFrag to ARTIQ scheduler
        rid = self.submit_bo_run(
            param_vector = param_vector,
            row_idx      = row_idx,
            sample_idx   = sample_idx,
            m_samples    = m_samples,
            session_name = session_name,
            pipeline     = pipeline,
            priority     = priority,
        )

        # log job submission
        print(f" Submitted RID {rid} : "
             f"row {row_idx:03d}  sample {sample_idx:02d}/{m_samples-1:02d}")

        # step 3: wait for BOExperimentFrag to complete
        self.wait_for_run(rid,
                            poll_interval=poll_interval,
                            timeout=timeout)

        # step 4: read results broadcast by BOExperimentFrag.update_images()
        N, sx_mm, sy_mm = self.read_latest_results()
        
        # convert to SI units
        sx_m = sx_mm * 1e-3   
        sy_m = sy_mm * 1e-3

        return N, sx_m, sy_m


    def run_bo_iteration(self, param_vector, row_idx,
                          m_samples, session_name):
        """
        Runs all m repeated shots for one BO iteration.
        Calls tof_experiment (which calls BOExperimentFrag) m times.

        Inputs:
            - param_vector : (dictionary) input parameters
            - row_idx      : (integer) BO iteration index
            - m_samples    : (integer) number of repeated shots
            - session_name : (string) BO session name

        Outputs:
            - raw_shots : (dict) {
                "N"  : ((m,)array)  atom numbers
                "sx" : ((m,)array)  1/e radii in x-direction [m]
                "sy" : ((m,)array)  1/e radii in y-direction [m]
              }
        """
        # validate that the parameter values are within 
        # bounds before submitting to hardware
        param_names, param_values = read_param_dict(param_vector)
        param_bounds = get_param_bounds()

       
        for name, val in zip(param_names, param_values):
            if name in param_bounds:
                lo, hi     = param_bounds[name]
                in_bounds  = lo <= val <= hi
                if not in_bounds :
                    # flag parameters that are out of bounds
                    flag = "⚠ OUT OF BOUNDS"
                    print(f"    {name:<25s} = {val:10.4f}  [{lo}, {hi}]  {flag}")
                else:  
                    pass

        N_shots  = np.zeros(m_samples)
        sx_shots = np.zeros(m_samples)
        sy_shots = np.zeros(m_samples)

        for sample_idx in range(m_samples):
            print(f"\n  Shot {sample_idx + 1} / {m_samples}")

            # tof_experiment submits BOExperimentFrag once per shot
            N, sx, sy = self.tof_experiment(
                param_vector = param_vector,
                row_idx      = row_idx,
                sample_idx   = sample_idx,
                m_samples    = m_samples,
                session_name = session_name,
            )

            N_shots[sample_idx]  = N
            sx_shots[sample_idx] = sx
            sy_shots[sample_idx] = sy

        raw_shots = {
            "N"  : N_shots,
            "sx" : sx_shots,
            "sy" : sy_shots,
        }

        return raw_shots

    def submit_bo_run(self, param_vector, row_idx, sample_idx,
                      m_samples, session_name,
                      pipeline="main", priority=1):
        """
        Constructs the ARTIQ scheduler job and submits it.

        Inputs:
            - param_vector : (dictionary) input parameters
            - row_idx      : (integer) BO iteration index
            - m_samples    : (integer) number of repeated shots
            - session_name : (string) BO session name
            - pipeline     : (string)  ARTIQ pipeline, set to default="main"
            - priority     : (integer) scheduler priority

        Outputs:
            - rid : (integer) ARTIQ run ID. 
        """
        # build dictionary of ndscan overrides from param_vector
        ndscan_overrides = self._build_ndscan_overrides(
            param_vector = param_vector,
            row_idx      = row_idx,
            sample_idx   = sample_idx,
            m_samples    = m_samples,
            session_name = session_name,
        )

        # create the run ID for this specific submission
        rid = self.scheduler.submit(  
            pipeline_name = pipeline,
            # create experiment identifier dictionary
            expid = {                               
                "file"      : "src\solvers\artiq_tof_experiment.py",    # file path to BOExperiment
                "class_name": "BOExperiment",                           # name of class to run experiment   
                "arguments" : ndscan_overrides,                         # translated parameters
                "log_level" : 20,                                       # logs normal experiment messages 
            },
            priority = priority,   # queue ordering
            due_time = None,       # run as soon as the pipeline is free
            flush    = False,      # adds submission to the queue immediately
        )

        return rid


    def _build_ndscan_overrides(self, param_vector, row_idx,
                                sample_idx, m_samples, session_name):
        """
        Translates the BO parameter dictionary into ndscan argument
        overrides that BOExperimentFrag.build_fragment expects.

        Parameter paths mirror the setattr_param keys in BOExperimentFrag:
            - Top-level params : "param_name"
            - MOT sub-fragment : "MOT/param_name"

        Inputs:
            - param_vector : (dict) {bo_param_name: physical_value}
            - row_idx      : (int)
            - sample_idx   : (int)
            - m_samples    : (int)
            - session_name : (str)

        Outputs:
            - overrides : (dict) ndscan-compatible argument dictionary
        """
        # create empty override dictionary
        overrides = {}

        #  add the BO session metadata 
        overrides["bo_session_name"] = session_name
        overrides["bo_row_idx"]      = float(row_idx)
        overrides["bo_sample_idx"]   = float(sample_idx)
        overrides["bo_m_samples"]    = float(m_samples)
        
        # map each parameter to the correct ndscan path : 
        
        # MOT parameters 
        # Path "MOT/loading_time" matches:
        #   self.mot = self.setattr_fragment("MOT", MOT)
        #   MOT.setattr_param("loading_time", ...)
        if "t_load_MOT" in param_vector:
            overrides["MOT/loading_time"] = param_vector["t_load_MOT"]

        if "delta_MOT" in param_vector:
            # Store as bo_* for saving in _save_bo_measurement
            # Actual MOT detuning set via EOM — path depends on your MOT fragment
            overrides["bo_delta_MOT"] = float(param_vector["delta_MOT"])

        if "P_MOT" in param_vector:
            overrides["bo_P_MOT"] = float(param_vector["P_MOT"])

        if "I_MOT" in param_vector:
            overrides["bo_I_MOT_current"] = float(param_vector["I_MOT"])

        #  CMOT parameters 
        if "t_ramp_CMOT" in param_vector:
            overrides["MOT/CMOT_duration"] = param_vector["t_ramp_CMOT"]

        if "delta_CMOT" in param_vector:
            # Convert Gamma to Hz for MOT fragment
            overrides["MOT/CMOT_detuning"] = (
                param_vector["delta_CMOT"] * 6.065e6
            )
            overrides["bo_delta_CMOT"] = float(param_vector["delta_CMOT"])

        if "delta_repump_CMOT" in param_vector:
            overrides["MOT/CMOT_Repump_power_attenuation"] = (
                param_vector["delta_repump_CMOT"]
            )
            overrides["bo_delta_repump_CMOT"] = float(
                param_vector["delta_repump_CMOT"]
            )

        if "t_hold_CMOT" in param_vector:
            overrides["MOT/CMOT_settle_time"] = param_vector["t_hold_CMOT"]

        if "I_CMOT" in param_vector:
            overrides["bo_I_CMOT_current"] = float(param_vector["I_CMOT"])

        if "P_repump_CMOT" in param_vector:
            overrides["bo_P_repump_CMOT"] = float(
                param_vector["P_repump_CMOT"]
            )

        #  PGC parameters 
        if "t_ramp_PGC" in param_vector:
            overrides["MOT/PGC_duration"] = param_vector["t_ramp_PGC"]

        if "delta_PGC" in param_vector:
            overrides["MOT/PGC_detuning"] = (
                param_vector["delta_PGC"] * 6.065e6
            )
            overrides["bo_delta_PGC"] = float(param_vector["delta_PGC"])

        if "t_hold_PGC" in param_vector:
            overrides["MOT/PGC_settle_time"] = param_vector["t_hold_PGC"]

        if "I_bias_x_PGC" in param_vector:
            overrides["bo_I_bias_x_PGC"] = float(
                param_vector["I_bias_x_PGC"]
            )
        if "I_bias_y_PGC" in param_vector:
            overrides["bo_I_bias_y_PGC"] = float(
                param_vector["I_bias_y_PGC"]
            )
        if "I_bias_z_PGC" in param_vector:
            overrides["bo_I_bias_z_PGC"] = float(
                param_vector["I_bias_z_PGC"]
            )

        # CDT parameters 
        if "P1_init_CDT" in param_vector:
            overrides["MOT/power_dimple"]   = param_vector["P1_init_CDT"]
            overrides["bo_P1_init_CDT"]     = float(param_vector["P1_init_CDT"])

        if "P2_init_CDT" in param_vector:
            overrides["MOT/power_reservoir"] = param_vector["P2_init_CDT"]
            overrides["bo_P2_init_CDT"]      = float(param_vector["P2_init_CDT"])

        if "P1_final_CDT" in param_vector:
            overrides["bo_P1_final_CDT"] = float(param_vector["P1_final_CDT"])

        if "P2_final_CDT" in param_vector:
            overrides["bo_P2_final_CDT"] = float(param_vector["P2_final_CDT"])

        if "t_evap" in param_vector:
            overrides["MOT/evaporation_duration1"] = param_vector["t_evap"]
            overrides["bo_t_evap"]                 = float(param_vector["t_evap"])

        if "t_cool_ramp_down" in param_vector:
            overrides["bo_cool_ramp_down"] = float(
                param_vector["t_cool_ramp_down"]
            )
        if "t_coil_ramp_down" in param_vector:
            overrides["bo_coil_ramp_down"] = float(
                param_vector["t_coil_ramp_down"]
            )
        if "t_ODT_ramp_up" in param_vector:
            overrides["bo_ramp_ODT"] = float(param_vector["t_ODT_ramp_up"])

        if "delay_1" in param_vector:
            overrides["bo_delay_1"] = float(param_vector["delay_1"])

        if "delay_2" in param_vector:
            overrides["bo_delay_2"] = float(param_vector["delay_2"])

        # Imaging 
        if "expansion_time" in param_vector:
            overrides["expansion_time"] = param_vector["expansion_time"]

        return overrides


    def wait_for_run(self, rid, poll_interval=0.5, timeout=300):
        """
        Block until the submitted run completes

        Inputs: 
            - rid           : (integer)  run ID returned by submit_bo_run
            - poll_interval : (float) seconds between status checks
            - timeout       : (float) maximum wait time in seconds

        Outputs:
            - True if completed successfully, raises RuntimeError on timeout
        """
    
        elapsed = 0.0

        while elapsed < timeout:
            # Get current run status from scheduler
            status = self.scheduler.get_status()

            # Check if our rid is still in the queue or running
            active_rids = set(status.keys())
            if rid not in active_rids:
                # Run has completed and been removed from scheduler
                return True

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise RuntimeError(
            f"Run {rid} did not complete within {timeout}s timeout"
        )


    def read_latest_results(self):
        """
        Read the most recent (N, sx, sy) from ARTIQ datasets.
        These are broadcast by update_images() in AbsorptionImageExpFrag.

        Outputs: 
            - N  : (float) atom number
            - sx : (float) sigma_x in mm
            - sy : (float) sigma_y in mm
        """
        N  = self.datasets.get("ndscan.points.channel_atom_number")
        sx = self.datasets.get("ndscan.points.channel_sigmax_mm")
        sy = self.datasets.get("ndscan.points.channel_sigmay_mm")

        return float(N[-1]), float(sx[-1]), float(sy[-1])


    def close(self):
        """Close RPC connections to ARTIQ master."""
        self.scheduler.close_rpc()
        self.datasets.close_rpc()