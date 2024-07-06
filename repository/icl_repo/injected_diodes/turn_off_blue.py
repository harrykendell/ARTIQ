import logging

from artiq.experiment import EnvExperiment
from koheron_ctl200_laser_driver import CTL200

logger = logging.getLogger(__name__)


class TurnOffBlue(EnvExperiment):
    """Turn off all the blue injected diodes"""

    def run(self):
        controller_names = [
            k
            for k, v in self.get_device_db().items()
            if (
                ("type" in v and v["type"] == "controller")
                and (
                    "command" in v
                    and "aqctl_koheron_ctl200_laser_driver" in v["command"]
                )
            )
        ]
        if not controller_names:
            raise ValueError("No CTL200 Koheron controllers found in device_db")

        for controller_name in controller_names:
            controller: CTL200 = self.get_device(controller_name)
            logger.info("Turning off controller %s", controller_name)
            controller.turn_off()
