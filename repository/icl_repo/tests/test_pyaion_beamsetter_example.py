from artiq.experiment import kernel
from ndscan.experiment import Fragment
from utils.beam_setter import ControlBeamsWithoutCoolingAOM
from utils.models import SUServoedBeam

my_beam = SUServoedBeam(
    name="my_blue_beam_for_physics_stuff",
    frequency="150e6",
    attenuation=20,
    suservo_device="suservo_aom_singlepass_461_2DMOT_A",
    shutter_device="TTL_shutter_461_2dmot_is_it_a",
    shutter_delay=20e-3,
)


class MyBeamTurnerOnnerer(Fragment):
    def build_fragment(self):
        self.setattr_fragment(
            "my_beam_setter",
            ControlBeamsWithoutCoolingAOM,
            beam_infos=[my_beam],
        )
        self.my_beam_setter: ControlBeamsWithoutCoolingAOM

    @kernel
    def turn_on_the_beam(self):
        self.core.break_realtime()
        self.my_beam_setter.turn_beams_on()

    @kernel
    def turn_off_the_beam(self):
        self.core.break_realtime()
        self.my_beam_setter.turn_beams_off()
