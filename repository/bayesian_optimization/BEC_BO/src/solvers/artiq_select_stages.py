
from pathlib import Path
from datetime import datetime
import json
import numpy as np

from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, s

from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatParam,
    StringParam,
    make_fragment_scan_exp,
)
from ndscan.experiment.parameters import (
    BoolParamHandle,
    FloatParamHandle,
    StringParamHandle,
)

from artiq.coredevice.core import Core
from src.globals import get_cooling_stages,  get_param_bounds
from src.utils.param_selection import select_active_params, active_bounds_arrays

cooling_stages = get_cooling_stages()
param_bounds = get_param_bounds()
param_names = list(param_bounds.keys())

class BOConfigFrag(ExpFragment):
    """
    Configuration of the BO session.
    """
    # The user sets which stages to optimize via the GUI.
        # - assembles the active parameter list and bounds
        # - writes them to Artiq datasets
        # - saves a session config

    def build_fragment(self):

        self.setattr_device("core")
        self.core: Core

        # Select cooling stages to optimize : set by user 
        self.opt_mot: BoolParamHandle = self.setattr_param(
            "opt_mot", BoolParam,
            "Optimise MOT parameters",
            default=False,
        )
        self.opt_cmot: BoolParamHandle = self.setattr_param(
            "opt_cmot", BoolParam,
            "Optimise CMOT parameters",
            default=False,
        )
        self.opt_pgc: BoolParamHandle = self.setattr_param(
            "opt_pgc", BoolParam,
            "Optimise PGC parameters",
            default=False,
        )
        self.opt_cdt: BoolParamHandle = self.setattr_param(
            "opt_cdt", BoolParam,
            "Optimise CDT parameters",
            default=False,
        )

        # Define session metadata 
        self.bo_session_name: StringParamHandle = self.setattr_param(
            "bo_session_name", StringParam,
            "BO session name",
            default="bo_session_001",
        )
        self.bo_m_samples: FloatParamHandle = self.setattr_param(
            "bo_m_samples", FloatParam,
            "Repeated shots per experimental run",
            default=5.0, min=1.0,
        )
        self.bo_n_init: FloatParamHandle = self.setattr_param(
            "bo_n_init", FloatParam,
            "Number of initialisation shots",
            default=20.0, min=5.0,
        )
        self.bo_n_iterations: FloatParamHandle = self.setattr_param(
            "bo_n_iterations", FloatParam,
            "Number of BO iterations after initialisation",
            default=50.0, min=1.0,
        )


    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.device_setup_subfragments()


    @kernel
    def run_once(self):
        """
        Kernel entry point.
        """
        self.core.break_realtime()
        self._configure_session()


    @rpc
    def _configure_session(self):
        """
        Read the opt_* flags, build the active parameter list,
        write to Artiq datasets, and save the config.
        """

        # Determine which stages are selected 
        selected_stages = {}
        if self.opt_mot.get():
            selected_stages["mot"]  = cooling_stages["mot"]
        if self.opt_cmot.get():
            selected_stages["cmot"] = cooling_stages["cmot"]
        if self.opt_pgc.get():
            selected_stages["pgc"]  = cooling_stages["pgc"]
        if self.opt_cdt.get():
            selected_stages["cdt"]  = cooling_stages["cdt"]

        if not selected_stages:
            raise ValueError(
                "No optimisation stages selected. "
                "Enable at least one of: opt_mot, opt_cmot, opt_pgc, opt_cdt"
            )

        # Create list of active parameters and bounds 
        _, active_params = select_active_params(selected_stages)

        active_bounds_lower, active_bounds_upper = active_bounds_arrays(active_params, param_bounds)
        
        # Session metadata 
        session_name = self.bo_session_name.get()
        m_samples     = int(self.bo_m_samples.get())
        n_init        = int(self.bo_n_init.get())
        n_iterations  = int(self.bo_n_iterations.get())
        date          = datetime.now().strftime("%Y-%m-%d")
        timestamp     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Log the session summary 
        print(f"\n{'='*55}")
        print("  BO Session Configuration")
        print(f"{'='*55}")
        print(f"  Campaign     : {session_name}")
        print(f"  Date         : {date}")
        print(f"  Stages       : {list(selected_stages.keys())}")
        print(f"  Parameters   : {len(active_params)}")
        print(f"  LHS init     : {n_init} shots")
        print(f"  BO iterations: {n_iterations}")
        print(f"  Shots/iter   : {m_samples}")
        print("\n  Active parameters:")
        for p in active_params:
            lo, hi = param_bounds[p]
            print(f"    {p:<25s}  [{lo}, {hi}]")
        print(f"{'='*55}\n")

        # Save info to an Artiq dataset (to be accessed in BO)
        self.set_dataset(
            "bo_config.session_name",
            session_name, broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.active_params",
            json.dumps(active_params), broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.bounds_lower",
            active_bounds_lower, broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.bounds_upper",
            active_bounds_upper, broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.selected_stages",
            json.dumps(list(selected_stages.keys())),
            broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.m_samples",
            m_samples, broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.n_init",
            n_init, broadcast=True, persist=True,
        )
        self.set_dataset(
            "bo_config.n_iterations",
            n_iterations, broadcast=True, persist=True,
        )
    

        # Save config dictionary as a JSON file
        config = {
            "metadata": {
                "session_name" : session_name,
                "date"          : date,
                "timestamp"     : timestamp,
            },
            "optimisation": {
                "selected_stages" : list(selected_stages.keys()),
                "active_params"   : active_params,
                "n_params"        : len(active_params),
                "n_init"          : n_init,
                "n_iterations"    : n_iterations,
                "m_samples"       : m_samples,
            },
            "bounds": {
                p: {"lower": param_bounds[p][0],
                    "upper": param_bounds[p][1]}
                for p in active_params
            },
        }

        config_folder = (
            Path("repository")
            / "bayesian_optimization"
            / "BEC_BO"
            / "outputs"
            / "results"
            / date
            / session_name
        )
        config_folder.mkdir(parents=True, exist_ok=True)

        config_path = config_folder / "session_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        print(f"Config saved to: {config_path}")


BOConfig = make_fragment_scan_exp(BOConfigFrag)

