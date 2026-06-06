from enum import Enum
import logging
import time
 
from matplotlib.path import Path
import numpy as np
 
from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import delay, delay_mu, host_only, kernel, rpc
from artiq.language.units import ms, s, us
from ndscan.experiment import (
    ExpFragment,
    FloatParam,
    Fragment,
    make_fragment_scan_exp,
    EnumParam,
    ParamHandle,
)
from ndscan.experiment.parameters import FloatParamHandle
 
logger = logging.getLogger(__name__)
logging.getLogger("pco").setLevel(logging.WARNING)
from repository.Tekscope.mso24 import MSO24
 
# import time
from time import time, strftime
 
# imort mkdir
from pathlib import Path
 
DEFAULT_IP = "192.168.0.5"
 
channels = ["1", "2", "3", "4"]
 
 
class TekscopeExp(Fragment):
    def build_fragment(self, single_acquisition=False):
        """Fragment to control the Tekscope oscilloscope and save screenshots and channel data"""
 
        """if single aquisition is on True then tekscope set the trigger mode to single and wait for the trigger before saving the screenshot and channel data, this is set when experiment starts"""
 
        self.setattr_device("core")
        self.core: Core
 
        self.setattr_param(
            "timebase",
            FloatParam,
            "The timebase of the oscilloscope in seconds per division",
            default=1 * ms,
        )
        self.setattr_param(
            "num_points",
            FloatParam,
            "The number of points to acquire",
            default=1000,
        )
 
        self.use_single_acquisition = single_acquisition
 
    @host_only
    def host_setup(self):
        tek = MSO24(DEFAULT_IP, save_dir=self.make_new_folder())
        tek.connect()
        self.tek = tek
        if self.use_single_acquisition:
            self.single_acquisition_on()
        super().host_setup()
        logger.info(f"Connected to Tekscope at {DEFAULT_IP}")
 
    @host_only
    def host_cleanup(self):
        if hasattr(self, "tek"):
            self.tek.close()
        else:
            logger.warning("Tekscope was not connected during cleanup.")
        super().host_cleanup()
 
    @host_only
    def save_screenshot(self, timeout=2 * s):
        filename = self.tek.screenshot()
        logger.info(f"Saved oscilloscope screenshot to {filename}")
        # Wait for the file to be fully written
        start_time = time()
        while not filename.exists():
            if time() - start_time > timeout:
                logger.error(
                    f"Timeout while waiting for screenshot file {filename} to be created."
                )
                return
            time.sleep(0.1)  # Check every 100 ms
 
    @host_only
    def save_all_channels(self, timeout=5 * s):
        """Save all channel data to CSV files and wait for them to be fully written"""
        # make folder with experiment name and timestamp to save the files in
        files = self.tek.save_all_channels()
        logger.info(f"Saved all channel data to: {files}")
        # Wait for the files to be fully written
        start_time = time()
        for file in files:
            while not file.exists():
                if time() - start_time > timeout:
                    logger.error(
                        f"Timeout while waiting for channel data file {file} to be created."
                    )
                    return
                time.sleep(0.1)  # Check every 100 ms
 
    @host_only
    def single_acquisition_on(self):
        """Perform a single acquisition on the Tekscope and save the screenshot and channel data"""
        self.tek.write("ACQUIRE:STATE RUN")
 
    @host_only
    def make_new_folder(self, base_path="/home/ae19663/Desktop/tekscope_files"):
        """Make a new folder with the current timestamp to save the files in"""
        timestamp = strftime("%Y%m%d_%H%M%S")
        new_folder = Path(base_path) / f"tekscope_{timestamp}"
        new_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created new folder for Tekscope files: {new_folder}")
        # return the path to the new folder
        return new_folder
 