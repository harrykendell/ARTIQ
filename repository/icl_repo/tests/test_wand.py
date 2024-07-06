from artiq.experiment import *
from wand.server import ControlInterface as WANDControlInterface


class TestWANDControl(EnvExperiment):
    def build(self):
        self.setattr_device("wand_server")
        self.wand_server: WANDControlInterface

    def run(self):
        lasers = self.wand_server.get_laser_db()
        for laser in lasers:
            meas = self.wand_server.get_freq(
                laser,
                priority=3,
                get_osa_trace=False,
                blocking=True,
                mute=False,
                offset_mode=False,
            )
            print(f"{laser} --- {meas}")
