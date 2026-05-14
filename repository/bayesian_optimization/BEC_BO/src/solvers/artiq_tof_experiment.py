from time import time
from pathlib import Path
from datetime import datetime
import json
import numpy as np

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us

from ndscan.experiment import (
    BoolParam,
    EnumParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    IntParam,
    OpaqueChannel,
    StringParam,
    make_fragment_scan_exp,
)

from artiq.coredevice.ttl import TTLInOut
from ndscan.experiment.parameters import (
    BoolParamHandle,
    FloatParamHandle,
    IntParamHandle,
    ParamHandle,
    StringParamHandle,
)
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera, ROI
from repository.imaging.processor import AbsImage, AbsImageSettings
from repository.models.devices import SUServoedBeam


# Path to save BO results
RESULTS_ROOT = (
    Path("repository")
    / "bayesian_optimization"
    /"BEC_BO"
    /"data"
    /"raw"
)

import numpy as np
import pandas as pd

 # Add the following units to Artiq (if not there) : mW, Gamma, A

class BOExperimentFrag(ExpFragment):
    """
    Perform BO and TOF measurements
    """

    def build_fragment(self):
        
        # Setup the devices
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        self.setattr_device("ccb")

        self.setattr_fragment("pco_camera", PcoCamera, num_images=3)
        self.pco_camera: PcoCamera

        self.img_beam: ControlBeamsWithoutCoolingAOM = self.setattr_fragment(
            "img_beam", ControlBeamsWithoutCoolingAOM,
            [SUServoedBeam["IMG"]]
        )

        self.setattr_device("moving_stage_ttl")
        self.moving_stage_trigger: TTLInOut = self.moving_stage_ttl

        self.mot: MOT = self.setattr_fragment("MOT", MOT, manual_init=False)

        # Set imaging parameters
        self.setattr_param_rebind(
            "exposure_time", self.pco_camera, "exposure_time",
            default=0.11 * ms
        )
        self.exposure_time: FloatParamHandle

        self.setattr_param(
            "magnification", FloatParam,
            "Magnification for imaging",
            default=1.0,
        )
        self.magnification: FloatParamHandle

        self.setattr_param(
            "imaging_roi", EnumParam,
            "Select imaging ROI",
            default=ROI.FULL, enum_class=ROI,
        )
        self.imaging_roi: ParamHandle

        self.setattr_param(
            "expansion_time", FloatParam,
            "Expansion time before imaging",
            default=0.5 * ms, min=1.0 * us, unit="ms",
        )
        self.expansion_time: FloatParamHandle

        self.odt_hold_time: FloatParamHandle = self.setattr_param(
            "ODT_hold_time", FloatParam,
            "Hold time in ODT after CMOT/PGC before imaging",
            default=50.0 * ms, min=0.0 * ms, unit="ms",
        )

        self.release_time: FloatParamHandle = self.setattr_param(
            "release_time", FloatParam,
            "Time to release the atoms",
            default=1.0 * ms, min=0.0 * ms, unit="ms",
        )

        self.hold_timeafter_release: FloatParamHandle = self.setattr_param(
            "hold_timeafter_release", FloatParam,
            "Hold time after releasing the atoms",
            default=1.0 * ms, min=0.0 * ms, unit="ms",
        )

        #  Select (sub-Doppler) cooling stages
        self.do_cmot: BoolParamHandle = self.setattr_param(
            "do_cmot", BoolParam, "Do the CMOT step", default=False
        )
        self.do_pgc: BoolParamHandle = self.setattr_param(
            "do_pgc", BoolParam, "Do the PGC step", default=False
        )
        self.odt_active: BoolParamHandle = self.setattr_param(
            "ODT_active", BoolParam, "ODT beams active", default=False,
        )
        self.do_evaporation1: BoolParamHandle = self.setattr_param(
            "do_evaporation1", BoolParam,
            "Do the evaporation step 1", default=False,
        )
        self.do_evaporation2: BoolParamHandle = self.setattr_param(
            "do_evaporation2", BoolParam,
            "Do the evaporation step 2", default=False,
        )
        self.trap_frequency_odt: BoolParamHandle = self.setattr_param(
            "trap_frequency", BoolParam,
            "Do the trap frequency step", default=False
        )


        # Define the result channels 
        self.atom_number: FloatChannel = self.setattr_result("atom_number")
        self.sigmax_mm: FloatChannel   = self.setattr_result("sigmax_mm")
        self.sigmay_mm: FloatChannel   = self.setattr_result("sigmay_mm")
        self.phase_space_density: FloatChannel = self.setattr_result(
            "phase_space_density"
        )
        self.info: OpaqueChannel = self.setattr_result("info", OpaqueChannel)
        self.gaussian_fit_centre_x: FloatChannel = self.setattr_result(
            "gaussian_fit_centre_x"
        )
        self.gaussian_fit_centre_y: FloatChannel = self.setattr_result(
            "gaussian_fit_centre_y"
        )

        #  BO metadata 
        self.bo_session_name: StringParamHandle = self.setattr_param(
            "bo_session_name", StringParam,
            "BO session name",
            default="bo_session_001",
        )
        self.bo_row_idx: FloatParamHandle = self.setattr_param(
            "bo_row_idx", FloatParam,
            "BO iteration / row index",
            default=0.0, min=0.0,
        )
        self.bo_sample_idx: FloatParamHandle = self.setattr_param(
            "bo_sample_idx", FloatParam,
            "BO sample index within current iteration (0 to m-1)",
            default=0.0, min=0.0,
        )
        self.bo_m_samples: FloatParamHandle = self.setattr_param(
            "bo_m_samples", FloatParam,
            "Total number of repeated shots per BO iteration",
            default=5.0, min=1.0,
        )

        # Define BO parameters
        # 1. MOT 
        self.bo_delta_MOT: FloatParamHandle = self.setattr_param(
            "bo_delta_MOT", FloatParam,
            "BO param: MOT detuning",
            default=2.0, unit="Gamma",
        )
        self.bo_P_MOT: FloatParamHandle = self.setattr_param(
            "bo_P_MOT", FloatParam,
            "BO param: MOT power",
            default=75.0, unit="mW",
        )
        self.bo_I_MOT_current: FloatParamHandle = self.setattr_param(
            "bo_I_MOT_current", FloatParam,
            "BO param: MOT coil current",
            default=1.0, unit="A",
        )
        self.bo_t_MOT: FloatParamHandle = self.setattr_param(
            "bo_t_MOT", FloatParam,
            "BO param: MOT loading time",
            default=10.0, unit="s",
        )

        # 2. CMOT 
        self.bo_delta_CMOT: FloatParamHandle = self.setattr_param(
            "bo_delta_CMOT", FloatParam,
            "BO param: CMOT detuning",
            default=4.0, unit="Gamma",
        )
        self.bo_delta_repump_CMOT: FloatParamHandle = self.setattr_param(
            "bo_delta_repump_CMOT", FloatParam,
            "BO param: CMOT repump detuning",
            default=2.0, unit="Gamma",
        )
        self.bo_P_repump_CMOT: FloatParamHandle = self.setattr_param(
            "bo_P_repump_CMOT", FloatParam,
            "BO param: CMOT repump power",
            default=3.0, unit="mW",          
        )
        self.bo_I_CMOT_current: FloatParamHandle = self.setattr_param(
            "bo_I_CMOT_current", FloatParam,
            "BO param: CMOT coil current",
            default=1.0, unit="A",
        )
        self.bo_ramp_CMOT: FloatParamHandle = self.setattr_param(
            "bo_ramp_CMOT", FloatParam,
            "BO param: CMOT ramp time",
            default=20.0, unit="ms",
        )
        self.bo_hold_CMOT: FloatParamHandle = self.setattr_param(
            "bo_hold_CMOT", FloatParam,
            "BO param: CMOT hold time",
            default=0.0, unit="ms",
        )

        # 3. PGC 
        self.bo_delta_PGC: FloatParamHandle = self.setattr_param(
            "bo_delta_PGC", FloatParam,
            "BO param: PGC detuning",
            default=7.0, unit="Gamma",
        )
        self.bo_I_bias_x_PGC: FloatParamHandle = self.setattr_param(
            "bo_I_bias_x_PGC", FloatParam,
            "BO param: PGC x-axis bias current",
            default=0.0, unit="A",
        )
        self.bo_I_bias_y_PGC: FloatParamHandle = self.setattr_param(
            "bo_I_bias_y_PGC", FloatParam,
            "BO param: PGC y-axis bias current",
            default=0.0, unit="A",
        )
        self.bo_I_bias_z_PGC: FloatParamHandle = self.setattr_param(
            "bo_I_bias_z_PGC", FloatParam,
            "BO param: PGC z-axis shim current",
            default=0.1, unit="A",
        )
        self.bo_ramp_PGC: FloatParamHandle = self.setattr_param(
            "bo_ramp_PGC", FloatParam,
            "BO param: PGC ramp time",
            default=30.0, unit="ms",
        )
        self.bo_hold_PGC: FloatParamHandle = self.setattr_param(
            "bo_hold_PGC", FloatParam,
            "BO param: PGC hold time",
            default=0.0, unit="ms",
        )

        # 4. CDT
        self.bo_P1_init_CDT: FloatParamHandle = self.setattr_param(
            "bo_P1_init_CDT", FloatParam,       
            "BO param: CDT beam 1 initial power",
            default=10.0, unit="W",
        )
        self.bo_P2_init_CDT: FloatParamHandle = self.setattr_param(
            "bo_P2_init_CDT", FloatParam,    
            "BO param: CDT beam 2 initial power",
            default=1.0, unit="W",
        )
        self.bo_P1_final_CDT: FloatParamHandle = self.setattr_param(
            "bo_P1_final_CDT", FloatParam,
            "BO param: CDT beam 1 final power",
            default=50.0, unit="mW",
        )
        self.bo_P2_final_CDT: FloatParamHandle = self.setattr_param(
            "bo_P2_final_CDT", FloatParam,     
            "BO param: CDT beam 2 final power",
            default=50.0, unit="mW",
        )
        self.bo_delay_1: FloatParamHandle = self.setattr_param(
            "bo_delay_1", FloatParam,
            "BO param: delay between cooling laser ramp and ODT",
            default=5.0, unit="ms",
        )
        self.bo_delay_2: FloatParamHandle = self.setattr_param(
            "bo_delay_2", FloatParam,
            "BO param: delay between coil ramp and ODT ramp",
            default=3.0, unit="ms",
        )
        self.bo_cool_ramp_down: FloatParamHandle = self.setattr_param(
            "bo_cool_ramp_down", FloatParam,
            "BO param: cooling laser ramp down time",
            default=5.0, unit="ms",
        )
        self.bo_coil_ramp_down: FloatParamHandle = self.setattr_param(
            "bo_coil_ramp_down", FloatParam,   
            "BO param: coil ramp down time",
            default=5.0, unit="ms",
        )
        self.bo_ramp_ODT: FloatParamHandle = self.setattr_param(
            "bo_ramp_ODT", FloatParam,
            "BO param: ODT ramp up time",
            default=50.0, unit="ms",
        )
        self.bo_t_evap: FloatParamHandle = self.setattr_param(
            "bo_t_evap", FloatParam,
            "BO param: evaporation duration",
            default=10.0, unit="s",
        )


    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.device_setup_subfragments()
    
    @kernel
    def run_once(self):
        # Perform absorption imaging

        self.core.break_realtime()
        self.mot.calculate_dma_handles()
        self.core.break_realtime()

        self.mot.set_dimple_trap_power(self.mot.power_dimple.get())

        self.mot.load()
        if self.do_cmot.get():
            self.mot.compress(
                evaporation_active=(
                    self.do_evaporation1.get() or self.do_evaporation2.get()
                ),
                odt_active=self.odt_active.get(),
            )
            if self.do_pgc.get():
                self.mot.pgc()

        self.mot.drop(
            evaporation_active=(
                self.do_evaporation1.get() or self.do_evaporation2.get()
            ),
            odt_active=self.odt_active.get(),
            cmot_active=self.do_cmot.get(),
            pgc_active=self.do_pgc.get(),
        )

        if self.odt_active.get():
            delay(self.odt_hold_time.get())
            if not self.do_evaporation1.get() or self.do_evaporation2.get():
                self.mot.drop_dimple()
                self.mot.drop_reservoir()

        if self.trap_frequency_odt.get():
            delay(self.release_time.get())
            self.mot.on_reservoir()
            delay(self.hold_timeafter_release.get())
            self.mot.drop_reservoir()

        if self.do_evaporation1.get():
            self.mot.evaporation1(
                single_step_evaporation=not self.do_evaporation2.get()
            )
            if self.do_evaporation2.get():
                self.mot.evaporation2()

        delay(self.expansion_time.get())

        with parallel:
            self.img_beam.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())

        self.img_beam.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME - self.exposure_time.get())
        self.mot.clear_atoms()

        with parallel:
            self.img_beam.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME - self.exposure_time.get())

        self.pco_camera.capture_image()
        delay(self.pco_camera.BUSY_TIME)

        self.mot.init()
        self.mot.load(wait_for_load=False)

        self.core.wait_until_mu(now_mu())
        self.update_images()


    @rpc(flags={"async"})
    def update_images(self):
        """
        Retrieve images, compute absorption image results,
        push to ndscan channels, and save the full 
        measurement record to disk.
        """

        # Existing image retrieval and processing 
        images = self.pco_camera.retrieve_images(
            roi=self.imaging_roi.get(), timeout=1 * s
        )
        if images is None:
            raise RuntimeError("Failed to retrieve images from camera")

        for num, img_name in enumerate(["TOF", "REF", "BG"]):
            self.set_dataset(
                f"Images.absorption.{img_name}",
                images[num], broadcast=True
            )

        self.set_dataset(
            "Images.absorption.expansion_time",
            self.expansion_time.get(), broadcast=True,
        )
        self.set_dataset(
            "Images.absorption.timestamp",
            time(), broadcast=True,
        )

        settings = AbsImageSettings(magnification=self.magnification.get())
        self.set_dataset(
            "Images.absorption.settings",
            settings.to_dataset(), broadcast=True,
        )

        self.absimg = AbsImage(
            data=images[0],
            ref=images[1],
            bg=images[2],
            settings=settings,
        )

        #  channel pushes 
        self.atom_number.push(self.absimg.atom_number)
        self.info.push(self.absimg.all_info())
        self.sigmax_mm.push(self.absimg.sigmax)
        self.sigmay_mm.push(self.absimg.sigmay)
        self.phase_space_density.push(self.absimg.phase_space_density_1)
        self.gaussian_fit_centre_x.push(self.absimg.x0)
        self.gaussian_fit_centre_y.push(self.absimg.y0)

        # BO data saving
        self._save_bo_measurement()


    def _save_bo_measurement(self):
        """
        Build the measurement dictionary and save to disk.
        Saves the results to a folder in Artiq directory
        assigned for the Bayesian Optimization.
        """

        date      = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        row_idx    = int(self.bo_row_idx.get())
        sample_idx = int(self.bo_sample_idx.get())
        m_samples  = int(self.bo_m_samples.get())
        session   = self.bo_session_name.get()

        # build save folder
        # repository/bayesian_optimization/experimental_results/
        #   ── YYYY-MM-DD/
        #         ── session_name/
        #               ── run_001/
        run_folder = (
            RESULTS_ROOT
            / date
            / session
            / f"run_{row_idx:03d}"
        )
        run_folder.mkdir(parents=True, exist_ok=True)

        # collect current BO parameters 
        parameters = {
            # MOT
            "delta_MOT"  : self.bo_delta_MOT.get(),                   
            "P_MOT"      : self.bo_P_MOT.get(),            
            "I_MOT"      : self.bo_I_MOT_current.get(),                    
            "t_load_MOT" : self.bo_t_MOT.get(),                   

            # CMOT
            "delta_CMOT"  : self.bo_delta_CMOT.get(),                     
            "delta_repump_CMOT"  : self.bo_delta_repump_CMOT.get(),              
            "P_repump_CMOT"      : self.bo_P_repump_CMOT.get(),        
            "I_CMOT"      : self.bo_I_CMOT_current.get(),                   
            "t_ramp_CMOT" : self.bo_ramp_CMOT.get(),         
            "t_hold_CMOT" : self.bo_hold_CMOT.get(),                

            # PGC
            "delta_PGC"  : self.bo_delta_PGC.get(),                  
            "I_bias_x_PGC" : self.bo_I_bias_x_PGC.get(),                  
            "I_bias_y_PGC" : self.bo_I_bias_y_PGC.get(),                  
            "I_bias_z_PGC" : self.bo_I_bias_z_PGC.get(),                
            "t_ramp_PGC" : self.bo_ramp_PGC.get(),            
            "t_hold_PGC" : self.bo_hold_PGC.get(),               
            
            # CDT
            "P1_init_CDT"       : self.bo_P1_init_CDT.get(),           
            "P2_init_CDT"       : self.bo_P2_init_CDT.get(),             
            "P1_final_CDT"      : self.bo_P1_final_CDT.get(),       
            "P2_final_CDT"      : self.bo_P2_final_CDT.get(),       
            "delay_1"           : self.bo_delay_1.get(),      
            "delay_2"           : self.bo_delay_2.get(),       
            "t_cool_ramp_down"  : self.bo_cool_ramp_down.get(),     
            "t_coil_ramp_down"  : self.bo_coil_ramp_down.get(),  
            "t_ODT_ramp_up"     : self.bo_ramp_ODT.get(),     
            "t_evap"            : self.bo_t_evap.get()             
        }

        #  build measurement dictionary 
        shot_dict = {

            "metadata": {
                "date"          : date,
                "timestamp"     : timestamp,
                "campaign_name" : session,
                "row_idx"       : row_idx,
                "sample_idx"    : sample_idx,
                "m_samples"     : m_samples,
            },

            "parameters": parameters,

            # raw absorption measurements from this single shot
            "measurement": {
                "N"     : float(self.absimg.atom_number),
                "sx_mm" : float(self.absimg.sigmax),
                "sy_mm" : float(self.absimg.sigmay),
                "sx_m"  : float(self.absimg.sigmax) * 1e-3,
                "sy_m"  : float(self.absimg.sigmay) * 1e-3,
                "psd"   : float(self.absimg.phase_space_density_1),
                "x0"    : float(self.absimg.x0),
                "y0"    : float(self.absimg.y0),
            },
        }

        # save individual shot JSON 
        shot_filename = (
            run_folder
            / f"shot_{row_idx:03d}_{sample_idx:02d}.json"
        )
        with open(shot_filename, "w") as f:
            json.dump(shot_dict, f, indent=2)

        # if this is the last sample, aggregate and save full record
        if sample_idx == m_samples - 1:
            self._save_full_record(run_folder, row_idx,
                                    session, date, parameters)

        # print(f"  BO shot saved: run {row_idx:03d} "
        #       f"sample {sample_idx:02d}/{m_samples-1:02d}  |  "
        #       f"N = {self.absimg.atom_number:.3e}  |  "
        #       f"sx = {self.absimg.sigmax:.3f} mm  |  "
        #       f"sx = {self.absimg.sigmax:.3f} mm  |  "
        #       f"psd = {self.absimg.phase_space_density_1:.3f} ")


    def _save_full_record(self, run_folder, row_idx,
                           session, date, parameters):
        """
        After all m shots are complete, load the individual shot
        JSONs, aggregate into statistics, and save the full record.
        Called automatically when sample_idx == m_samples - 1.
        """
        m = int(self.bo_m_samples.get())

        # load all individual shot files for this run
        N_shots  = np.zeros(m)
        sx_shots = np.zeros(m)
        sy_shots = np.zeros(m)

        for sample_idx in range(m):
            shot_file = (
                run_folder
                / f"shot_{row_idx:03d}_{sample_idx:02d}.json"
            )
            with open(shot_file, "r") as f:
                shot = json.load(f)

            N_shots[sample_idx]  = shot["measurement"]["N"]
            sx_shots[sample_idx] = shot["measurement"]["sx_m"]
            sy_shots[sample_idx] = shot["measurement"]["sy_m"]

        # compute statistics
        def stats(arr):
            return {
                "mean" : float(np.mean(arr)),
                "std"  : float(np.std(arr, ddof=1)),
                "sem"  : float(np.std(arr, ddof=1) / np.sqrt(m)),
                "min"  : float(np.min(arr)),
                "max"  : float(np.max(arr)),
            }

        full_record = {

            "metadata": {
                "date"          : date,
                "timestamp"     : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "campaign_name" : session,
                "row_idx"       : row_idx,
                "m_samples"     : m,
            },

            "parameters": parameters,

            "raw_shots": {
                "N"  : N_shots.tolist(),
                "sx" : sx_shots.tolist(),   # metres
                "sy" : sy_shots.tolist(),   # metres
            },

            "statistics": {
                "N"  : stats(N_shots),
                "sx" : stats(sx_shots),
                "sy" : stats(sy_shots),
            },
        }

        full_record_path = (
            run_folder
            / f"experiment_{row_idx:03d}_full_record.json"
        )
        with open(full_record_path, "w") as f:
            json.dump(full_record, f, indent=2)

        # print(f"\n  Full record saved: run {row_idx:03d}")
        # print(f"  N  = {full_record['statistics']['N']['mean']:.3e} "
        #       f"± {full_record['statistics']['N']['sem']:.2e}")
        # print(f"  sx = {full_record['statistics']['sx']['mean']*1e6:.2f} "
        #       f"± {full_record['statistics']['sx']['sem']*1e6:.3f} µm")
        # print(f"  sy = {full_record['statistics']['sy']['mean']*1e6:.2f} "
        #       f"± {full_record['statistics']['sy']['sem']*1e6:.3f} µm")
    
    
BOExperiment = make_fragment_scan_exp(BOExperimentFrag)


