import logging

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLOut
from artiq.experiment import delay
from artiq.experiment import kernel
from artiq.experiment import now_mu
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from icl_repo.lib.fragments.blue_3d_mot import Blue3DMOTFrag
from icl_repo.lib.fragments.cameras.dual_camera_measurer import BGCorrectedMeasurement


logger = logging.getLogger(__name__)


class MeasureMagneticTrapWithCameraFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("mot_controller", Blue3DMOTFrag)
        self.mot_controller: Blue3DMOTFrag

        self.setattr_fragment(
            "camera_interface", BGCorrectedMeasurement, hardware_trigger=True
        )
        self.camera_interface: BGCorrectedMeasurement

        # The repumpers are not yet driven by ARTIQ, but we do have access to their shutters
        self.repumper_707_shutter: TTLOut = self.get_device("ttl_shutter_repump_707")
        self.repumper_679_shutter: TTLOut = self.get_device("ttl_shutter_repump_679")

        self.setattr_param(
            "mot_loading_time",
            FloatParam,
            description="Time to wait for the 3D MOT to load",
            default=100e-3,
            min=0,
            unit="ms",
            step=1,
        )
        self.mot_loading_time: FloatParamHandle

        self.setattr_param(
            "dark_time",
            FloatParam,
            description="Time to wait in the dark for the magnetic trap",
            default=100e-3,
            min=0,
            unit="ms",
            step=1,
        )
        self.dark_time: FloatParamHandle

        self.setattr_param(
            "repump_shutter_time",
            FloatParam,
            description="Time to wait after repumping before imaging",
            default=10e-3,
            min=0,
            unit="ms",
            step=1,
        )
        self.repump_shutter_time: FloatParamHandle

        # Ensure that both cameras are on for the same length of time as the blue
        # fluorescence is pulsed
        self.setattr_param_rebind(
            "exposure",
            self.camera_interface,
            "exposure_horiz",
            default=1e-3,
            description="Camera exposure and fluorescence pulse length",
        )
        self.camera_interface.bind_param(
            "exposure_vert",
            self.exposure,
        )
        self.exposure: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.break_realtime()
        delay(20e-3)

        # Turn on the 2D/3D beams & AOMs,
        # but block the important ones, leaving the repumpers on
        self.mot_controller.enable_mot_defaults()
        delay(20e-9)
        self.mot_controller.turn_off_3d_and_2d_beams()

        delay(
            100e-3
        )  # Wait to allow atoms to disperse if there were any hanging around

        # Load MOT without repumpers
        self.repumper_707_shutter.off()
        self.repumper_679_shutter.off()
        delay(20e-3)  # Surely enough for the SRS shutters to close
        self.mot_controller.turn_on_3d_and_2d_beams()

        # Wait for the MOT to load
        delay(self.mot_loading_time.get())

        # Turn off the push and MOT beams
        self.mot_controller.turn_off_3d_and_2d_beams()

        # Wait for some time while the atoms sit in their magnetic trap
        delay(self.dark_time.get())

        # Turn on the MOT beams and the repumpers (but not the push beam)
        self.mot_controller.turn_on_3d_beams()
        delay(20e-9)
        self.mot_controller.turn_on_repumpers()
        delay(self.repump_shutter_time.get())

        # Take a photo
        self.camera_interface.trigger_signal()

        # Clear out the atoms
        delay(100e-3)
        self.mot_controller.turn_off_3d_beams()  # but leave repumps on
        delay(50e-3)
        self.mot_controller.turn_on_3d_beams()
        delay(10e-3)
        self.camera_interface.trigger_background()

        # Trigger the host to retrieve the data
        self.core.wait_until_mu(now_mu() + 1e-3)
        self.camera_interface.save_data()


MeasureMagneticTrapWithCamera = make_fragment_scan_exp(
    MeasureMagneticTrapWithCameraFrag
)
