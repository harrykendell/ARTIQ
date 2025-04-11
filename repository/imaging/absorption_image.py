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

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.stats import mode


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
            max=10.0 * ms,
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

        # release MOT and propagate cloud - we can't shutter as tof may be less than the delay
        with parallel:
            self.coil_setter.turn_off()
            self.mot_beam_setter.turn_beams_off(ignore_shutters=True)
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
        print("Updating images")
        images = self.pco_camera.retrieve_images(
            roi=self.pco_camera.FULL_ROI, timeout=10 * s
        )
        if images is None:
            raise RuntimeError("Failed to retrieve images from camera")

        # remove the background
        atoms = np.subtract(images[0], images[2])
        light = np.subtract(images[1], images[2])
        # normalize and threshold transmission based on the mode of the background
        threshold = mode(images[2]).mode[0]/2.
        transmission = np.divide(atoms, light, where=light > threshold)
        transmission[light <= threshold] = 1
        np.clip(transmission, a_min=0, a_max=1, out=transmission)
        # find the OD
        smoothed_transmission = gaussian_filter(transmission, sigma=1)
        od = -np.log(smoothed_transmission, where=smoothed_transmission > 0)
        self.set_dataset("Images.absorption.OD", od, persist=True)
        self.ccb.issue(
            "create_applet",
            "Optical Density",
            f"${{artiq_applet}}image Images.absorption.OD --server {server_addr}",
        )

        for num, img_name in enumerate(["TOF", "REF", "BG"]):
            # save for applet
            self.set_dataset(f"Images.absorption.{img_name}", images[num], persist=True)

            self.ccb.issue(
                "create_applet",
                f"{img_name}",
                f"${{artiq_applet}}image Images.absorption.{img_name} --server {server_addr}",
            )


AbsorptionImage = make_fragment_scan_exp(AbsorptionImageExpFrag)
