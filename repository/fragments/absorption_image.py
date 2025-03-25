from artiq.coredevice.core import Core
from artiq.experiment import kernel, rpc, delay, parallel
from artiq.language.units import ms, us
from device_db import server_addr

from ndscan.experiment import ExpFragment, make_fragment_scan_exp, FloatParam
from ndscan.experiment.parameters import FloatParamHandle

from repository.fragments.PCO_Camera import PcoCamera
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.fragments.beam_setter import ControlBeamsWithoutCoolingAOM
from repository.models.devices import SUSERVOED_BEAMS, VDRIVEN_SUPPLIES


MOT_SIZE = 40
MOT_X = 715
MOT_Y = 575
MOT_ROI = (MOT_X - MOT_SIZE, MOT_Y - MOT_SIZE, MOT_X + MOT_SIZE, MOT_Y + MOT_SIZE)


# Absorption imaging playground
class AbsorptionImageExpFrag(ExpFragment):
    """
    Allow the atoms to escape and then take an image
    """

    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")
        self.setattr_device("scheduler")

        self.setattr_fragment("pco_camera", PcoCamera)
        self.pco_camera: PcoCamera
        self.setattr_param_rebind("exposure_time", self.pco_camera, "exposure_time")

        self.setattr_fragment(
            "coil_setter",
            SetAnalogCurrentSupplies,
            [VDRIVEN_SUPPLIES["X1"], VDRIVEN_SUPPLIES["X2"]],
            init=False,
        )
        self.coil_setter: SetAnalogCurrentSupplies

        self.setattr_fragment(
            "mot_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUSERVOED_BEAMS["MOT"]],
        )
        self.mot_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_fragment(
            "img_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[SUSERVOED_BEAMS["IMG"]],
        )
        self.img_beam_setter: ControlBeamsWithoutCoolingAOM

        self.setattr_param(
            "expansion_time",
            FloatParam,
            "Expansion time before imaging",
            default=0.1 * ms,
            min=1.0 * us,
            max=10.0 * ms,
            unit="ms",
        )
        self.expansion_time: FloatParamHandle

    @kernel
    def run_once(self):
        self.core.break_realtime()
        delay(100 * ms)

        # By ignoring shutters we don't drop the MOT for `shutter_delay` time if it was already loaded
        self.mot_beam_setter.turn_beams_on(ignore_shutters=True)
        self.img_beam_setter.turn_beams_off()

        # image of loaded MOT
        self.pco_camera.capture_image()
        delay(150 * ms)

        # release MOT and propagate cloud
        with parallel:
            self.coil_setter.turn_off()
            self.mot_beam_setter.turn_beams_off(ignore_shutters=True)

        delay(self.expansion_time.get())

        # image cloud
        self.mot_beam_setter.turn_beams_on(ignore_shutters=True)
        self.pco_camera.capture_image()
        delay(self.expansion_time.get())
        self.mot_beam_setter.turn_beams_off()

        # background image
        delay(300 * ms)
        self.pco_camera.capture_image()

        # leave the MOT to reload
        self.core.break_realtime()
        self.coil_setter.set_defaults()
        self.mot_beam_setter.turn_beams_on()
        self.img_beam_setter.turn_beams_on()
        self.update_image()

    @rpc(flags={"async"})
    def update_image(self):
        images = self.pco_camera.retrieve_images()

        for num, img_name in enumerate(["MOT", "TOF", "BG"]):
            self.set_dataset(
                f"Images.Absorption.{img_name}", images[num], broadcast=True
            )

            self.ccb.issue(
                "create_applet",
                img_name,
                f"${{artiq_applet}}image Images.Absorption.{img_name} --server {server_addr}",
            )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
