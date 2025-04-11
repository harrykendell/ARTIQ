from artiq.coredevice.core import Core
from artiq.experiment import kernel, rpc, delay, parallel, now_mu
from artiq.language.units import s, ms, us
from device_db import server_addr

from ndscan.experiment import ExpFragment, make_fragment_scan_exp, FloatParam
from ndscan.experiment.parameters import FloatParamHandle, IntParamHandle

from repository.imaging.PCO_Camera import PcoCamera
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.models.devices import SUServoedBeam, VDrivenSupply


class ODTImageExpFrag(ExpFragment):
    """
    Dipole trap transfer imaging
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")

        self.setattr_fragment("pco_camera", PcoCamera, num_images=5)
        self.pco_camera: PcoCamera
        self.setattr_param_rebind("exposure_time", self.pco_camera, "exposure_time")
        self.exposure_time: FloatParamHandle

        self.setattr_fragment(
            "coil_setter",
            SetAnalogCurrentSupplies,
            VDrivenSupply["X1", "X2"],
            init=False,
        )
        self.coil_setter: SetAnalogCurrentSupplies

        self.setattr_fragment(
            "mot_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["MOT"]],
        )
        self.mot_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_fragment(
            "img_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["IMG"]],
        )
        self.img_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_fragment(
            "all_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=SUServoedBeam["MOT", "IMG"],
        )
        self.all_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_fragment(
            "odt_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUServoedBeam["CDT2"]],
        )
        self.odt_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_param(
            "hold_time_in_ODT",
            FloatParam,
            "Hold time in ODT before imaging",
            default=6 * ms,
            min=1.0 * us,
            max=10.0 * s,
            unit="ms",
        )
        self.hold_time_in_ODT: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.reset()

        for odt in [True, False]:
            self.core.break_realtime()
            self.coil_setter.turn_off()  # make sure we unload MOT
            delay(100 * ms)

            # By ignoring shutters we don't drop the MOT for `shutter_delay` time if it was already loaded
            self.mot_beam_setter.turn_beams_on()
            self.img_beam_setter.turn_beams_off(ignore_shutters=True)
            self.coil_setter.set_defaults()
            delay(10 * s)

            # initial image of loaded MOT
            if odt:
                self.pco_camera.capture_image()
            delay(self.exposure_time.get())
            delay(200 * ms)

            if odt:
                delay(0.1*us)
                self.odt_beam_setter.turn_beams_on()
            delay(100 * ms)

            # release MOT and propagate cloud
            # we can't shutter as tof may be less than the delay
            with parallel:
                self.coil_setter.turn_off()
                self.mot_beam_setter.turn_beams_off(ignore_shutters=True)
            delay(self.hold_time_in_ODT.get())

            # image cloud
            # don't shutter if using the mot beam to image as it interferes with the release stage
            with parallel:
                self.mot_beam_setter.turn_beams_on(ignore_shutters=True)
                self.pco_camera.capture_image()
            delay(self.exposure_time.get())
            self.mot_beam_setter.turn_beams_off(ignore_shutters=True)
            self.odt_beam_setter.turn_beams_off()

        delay(300 * ms)

        # reference image
        with parallel:
            self.mot_beam_setter.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.mot_beam_setter.turn_beams_off()
        delay(150 * ms)

        # background image
        self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        delay(150 * ms)

        # leave the MOT to reload
        self.coil_setter.set_defaults()
        self.mot_beam_setter.turn_beams_on()
        self.img_beam_setter.turn_beams_off()
        self.odt_beam_setter.turn_beams_off()

        self.core.wait_until_mu(now_mu())
        self.update_image()

    @rpc(flags={"async"})
    def update_image(self):
        name = "Images.odt"
        images = self.pco_camera.retrieve_images(roi=self.pco_camera.MOT_ROI)

        for num, img_name in enumerate(["MOT", "TOF", "NO_ODT_TOF", "REF", "BG"]):
            # save for propsperity
            self.set_dataset(f"{name}.{img_name}", images[num], persist=True)

            # save for applet
            self.set_dataset(f"Images.{img_name}", images[num], broadcast=True)

        self.set_dataset("Images.TOF-REF", images[1] - images[3], broadcast=True)
        self.ccb.issue(
            "create_applet",
            "TOF-REF",
            f"${{artiq_applet}}image Images.TOF-REF --server {server_addr}",
        )

        self.set_dataset("Images.TOF-NO_ODT_TOF", images[1] - images[2], broadcast=True)
        self.ccb.issue(
            "create_applet",
            "TOF-NO_ODT_TOF",
            f"${{artiq_applet}}image Images.TOF-NO_ODT_TOF --server {server_addr}",
        )


ODTImage = make_fragment_scan_exp(ODTImageExpFrag)
