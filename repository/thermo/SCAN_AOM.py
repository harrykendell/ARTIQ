from time import time
 
from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.experiment import kernel, rpc
from artiq.language import delay, ms, now_mu, parallel, s, us, MHz
 
# from repository.models.device_db import server_addr
from ndscan.experiment import (
    BoolParam,
    ExpFragment,
    FloatChannel,
    FloatParam,
    OpaqueChannel,
    make_fragment_scan_exp,
)
 
from artiq.coredevice.ttl import TTLInOut
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from repository.fragments.mot import MOT
from repository.imaging.PCO_Camera import PcoCamera
from repository.imaging.processor import AbsImage  # noqa: E402
from repository.models.devices import SUServoedBeam
from repository.Dipole_trap.moving_stage import MovingStage
 
from repository.fragments.suservo_frag import SUServoFrag
 
from repository.fragments.mot import FloatParamHandle
 
 
class SCAN_AOM(ExpFragment):
    """
    Scan AOM frequency and record response
    """
 
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core
 
        self.setattr_fragment(
            "SUServoFrag",
            SUServoFrag,
            SUServoedBeam["LATX"].suservo_device,
        )
        self.SUServoFrag: SUServoFrag
 
        self.start_freq: FloatParamHandle = self.setattr_param(
            "start_frequency",
            FloatParam,
            default=190.0 * MHz,
            unit="MHz",
            description="Start frequency of AOM scan",
        )
 
        self.stop_freq: FloatParamHandle = self.setattr_param(
            "stop_frequency",
            FloatParam,
            default=210.0 * MHz,
            unit="MHz",
            description="Stop frequency of AOM scan",
 
        )
        self.step_size: FloatParamHandle = self.setattr_param(
            "step_size",
            FloatParam,
            default=0.5 * MHz,
            unit="MHz",
            description="Step size of AOM scan",
        )
 
        self.integration_time: FloatParamHandle = self.setattr_param(
            "integration_time",
            FloatParam,
            default=20 * us,
            unit="us",
            description="Integration time for AOM scan",
        )
 
        self.amplitude_dds: FloatParamHandle = self.setattr_param(
            "amplitude_dds",
            FloatParam,
            default=0.5,
            unit="",
            description="Amplitude of DDS during scan, min=0 max=1",
        )
 
 
        manual_init= False
        self.manual_init: bool = manual_init
    def device_setup(self):
        self.device_setup_subfragments()
 
        if not self.manual_init:
            self.core.break_realtime()
            self.init()
 
    @kernel
    def init(self) -> None:
        """
        Initialize devices.
        **Timeline:** we break_realtime() after setting the devices
        """
        self.reset()
        self.core.break_realtime()
 
    @kernel
    def run_once(self) -> None:
        """
        Scan AOM frequency and record response
        """
        start_freq = self.start_freq.get()
        stop_freq = self.stop_freq.get()
        step_size = self.step_size.get()
        integration_time = self.integration_time.get()
 
        freq = start_freq
        while freq <= stop_freq:
            self.SUServoFrag.set_dds(profile=self.SUServoFrag.get_profile(), frequency=freq, offset=)
            delay(integration_time)
            # Here you would add code to record the response at this frequency
            freq += step_size
 
 
SCAN_AOM_experiment = make_fragment_scan_exp(SCAN_AOM)