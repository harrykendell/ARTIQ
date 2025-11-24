import logging
import time

from ndscan.experiment.result_channels import ResultChannel
import numpy as np
from repository.Thorlabs.KDC101_serial import KDC101

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut
from artiq.experiment import delay, delay_mu, host_only, kernel, rpc
from artiq.language.units import ms, s, us
from ndscan.experiment import ExpFragment, FloatParam, Fragment, make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParamHandle


class MovingStage(Fragment):
    """
    Fragment to control Thorlabs KDC101 moving stage
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("moving_stage_ttl")
        self.moving_stage_trigger: TTLInOut = self.moving_stage_ttl

        self.setattr_param(
            "moving_absolute_distance",
            FloatParam,
            "Distance to move the stage on trigger (mm)",
            default=0.0,
            min=0,
            max=10.0,
        )
        self.moving_absolute_distance: FloatParamHandle

    def host_setup(self):
        self.KDC101 = KDC101()
        self.KDC101.__init__()

        self.logger = logging.getLogger("MovingStage")
        self.logger.info("MovingStage initialized.")
        return super().host_setup()

    def host_cleanup(self):
        if self.KDC101 is not None:
            self.KDC101.close()
            self.logger.info("KDC101 connection closed.")
        super().host_cleanup()

    @kernel
    def device_setup(self) -> None:
        self.core.break_realtime()
        self.logger.info("Moving stage TTL set to output.")
        self.moving_stage_trigger.off()
        self.logger.info("Moving stage TTL set to low.")

    @rpc
    def set_stage_absolute(self, position_mm: float, sleep_time: float):
        """
        set the stage for moving to an absolute position in mm at specified speed in mm
        """
        if self.KDC101 is None:
            raise RuntimeError("KDC101 not initialized. Call host_setup first.")
        self.KDC101.set_abs_move_params(position_mm, sleep_time=sleep_time)
    
    @rpc
    def move_stage_absolute(self):
        """
        Move the stage to the absolute position set by moving_absolute_distance
        """
        if self.KDC101 is None:
            raise RuntimeError("KDC101 not initialized. Call host_setup first.")
        self.KDC101.move_stage_absolute()
        self.logger.info(
            f"Moving stage to absolute position {self.moving_absolute_distance.get()} mm."
        )

class MovingStage_exp(ExpFragment):
    """
    move the stage to an absolute position
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core
        
        self.setattr_fragment(
            "absolute_moving_stage", MovingStage
        )
        self.absolute_moving_stage: MovingStage

        self.setattr_param_rebind(
            "moving_absolute_distance",
            self.absolute_moving_stage,
            "moving_absolute_distance",
            default=1.0,
        )
        self.moving_absolute_distance: FloatParamHandle

    @kernel
    def run_once(self) -> None:
        self.absolute_moving_stage.set_stage_absolute(self.moving_absolute_distance.get())
        self.absolute_moving_stage.move_stage_absolute()
        return super().run_once()


movestagetoabsolute = make_fragment_scan_exp(MovingStage_exp)
