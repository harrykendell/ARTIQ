from artiq.coredevice.core import Core
from artiq.experiment import kernel, rpc, delay, parallel, now_mu
from artiq.language.units import s, ms, us
from device_db import server_addr

from ndscan.experiment import ExpFragment, make_fragment_scan_exp, FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from repository.imaging.PCO_Camera import PcoCamera
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.models.devices import SUServoedBeam, VDrivenSupply


class AbsorptionImageExpFrag(ExpFragment):
    """
    Absorption imaging of MOT expansion
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")

        self.setattr_fragment("pco_camera", PcoCamera, num_images=3)
        self.pco_camera: PcoCamera
        self.setattr_param_rebind(
            "exposure_time", self.pco_camera, "exposure_time", default=1 * ms
        )
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

        self.setattr_param(
            "load_time",
            FloatParam,
            "Time to load the MOT",
            default=10.0 * s,
            unit="s",
        )
        self.load_time: FloatParamHandle

        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=5.0 * ms,
            min=1.0 * us,
            unit="ms",
        )
        self.expansion_time: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.reset()

        self.coil_setter.turn_off()  # make sure we unload MOT
        delay(100 * ms)

        # load the MOT
        self.mot_beam_setter.turn_beams_on()
        self.img_beam_setter.turn_beams_off()
        self.coil_setter.set_defaults()
        delay(self.load_time.get())

        # release MOT and propagate cloud
        with parallel:
            self.coil_setter.turn_off()
            self.mot_beam_setter.turn_beams_off()
        delay(self.expansion_time.get())

        # image cloud
        with parallel:
            self.img_beam_setter.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam_setter.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME)

        # make sure the mot has cleared
        delay(100 * ms)

        # reference image
        with parallel:
            self.img_beam_setter.turn_beams_on()
            self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        self.img_beam_setter.turn_beams_off()
        delay(self.pco_camera.BUSY_TIME)

        # background image
        self.pco_camera.capture_image()
        delay(self.exposure_time.get())
        delay(self.pco_camera.BUSY_TIME)

        # leave the MOT to reload
        self.coil_setter.set_defaults()
        self.mot_beam_setter.turn_beams_on()
        self.img_beam_setter.turn_beams_off()

        self.core.wait_until_mu(now_mu())
        self.update_images()

    @rpc(flags={"async"})
    def update_images(self):
        images = self.pco_camera.retrieve_images(
            roi=self.pco_camera.FULL_ROI, timeout=10 * s
        )
        if images is None:
            raise RuntimeError("Failed to retrieve images from camera")

        for num, img_name in enumerate(["TOF", "REF", "BG"]):
            # save for applet
            self.set_dataset(
                f"Images.absorption.{img_name}", images[num], broadcast=True
            )
        self.set_dataset(
            "Images.absorption.expansion_time",
            self.expansion_time.get(),
            broadcast=True,
        )

        self.ccb.issue(
            "create_applet",
            "AbsorptionImage",
            f"${{python}} -m repository.imaging.applet --server {server_addr}"  # noqa: E501,
        )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
