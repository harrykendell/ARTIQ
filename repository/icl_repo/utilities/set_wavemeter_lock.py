from artiq.experiment import BooleanValue
from artiq.experiment import EnvExperiment
from artiq.experiment import NumberValue
from wand.server import ControlInterface as WandServer

LASERS = ["461", "689", "707", "679"]


def _laser_name_to_enabled_param(laser):
    return f"{laser}_enabled"


def _laser_name_to_offset_param(laser):
    return f"{laser}_offset"


class EnableWavemeterLock(EnvExperiment):
    """
    Enable or disable wavemeter locking with WAND
    """

    def build(self):
        self.setattr_device("wand_server")
        self.wand_server: WandServer

        for laser in LASERS:
            self.setattr_argument(
                _laser_name_to_enabled_param(laser),
                BooleanValue(default=True),
                group=laser,
            )
            self.setattr_argument(
                _laser_name_to_offset_param(laser),
                NumberValue(
                    default=0.0, unit="MHz", precision=1, type="float", step=1e5
                ),
                group=laser,
            )

    def run(self):
        for laser in LASERS:
            laser_enabled = getattr(self, _laser_name_to_enabled_param(laser))
            laser_offset = getattr(self, _laser_name_to_offset_param(laser))

            if laser_enabled:
                self.wand_server.lock(laser, set_point=laser_offset, timeout=None)
            else:
                self.wand_server.unlock(laser, name="")
