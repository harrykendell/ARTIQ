import logging

import requests
from ndscan.experiment import StringParam
from qbutler.calibration import Calibration
from qbutler.calibration import CalibrationResult

logger = logging.getLogger(__name__)


# Odd path to access, determined by sniffing the web client
RESOURCE_PATH = "!cDSSID:ae75bb64"


class MonitorTurbo(Calibration):
    """
    Monitor the pressure of a Leybold turbo
    """

    def build_calibration(self):
        self.setattr_param(
            "monitor_ip",
            StringParam,
            "IP of pump",
            default='"10.137.1.15"',
        )
        self.setattr_param(
            "description",
            StringParam,
            "Pump description",
            default='"turbo1"',
        )

        self.set_timeout(10)

    def check_own_state(self):
        info_str = requests.get(
            "http://" + self.monitor_ip.get() + "/" + RESOURCE_PATH
        ).text

        pressure_str = info_str.split("|")[3]
        pressure_1_str = pressure_str.split(";")[4]
        pressure_2_str = pressure_str.split(";")[5]

        pressure_1 = float(pressure_1_str.split(":")[1])
        pressure_2 = float(pressure_2_str.split(":")[1])

        logger.info("Pressures = %f / %f", pressure_1, pressure_2)

        return CalibrationResult.OK, {
            "tags": {"description": self.description.get()},
            "fields": {"pressure_1": pressure_1, "pressure_2": pressure_2},
        }
