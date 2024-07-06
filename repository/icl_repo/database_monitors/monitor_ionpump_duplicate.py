import logging
import re
from telnetlib import Telnet

from ndscan.experiment import StringParam
from qbutler.calibration import Calibration
from qbutler.calibration import CalibrationResult

logger = logging.getLogger(__name__)

COMMAND_PRESSURE = b"spc 0b 1\r\n"
COMMAND_CURRENT = b"spc 0a 1\r\n"


class MonitorIonPumpDup(Calibration):
    """
    Monitor the current and pressure of an ion pump
    """

    def build_calibration(self):
        self.setattr_param(
            "ip", StringParam, "IP of the ion pump", default='"10.137.1.16"'
        )
        self.setattr_param(
            "description",
            StringParam,
            "Description of the ion pump",
            default='"chamber2"',
        )

        self.set_timeout(30)

    def check_own_state(self):
        with Telnet(self.ip.get(), 23) as tn:
            logger.debug("Connected to ion pump at %s", self.ip.get())

            tn.read_until(b">", timeout=1)

            logger.debug("Querying ion pump pressure at %s", self.ip.get())

            tn.write(COMMAND_PRESSURE)
            response = tn.read_until(b">", 1)

            logger.debug("Response = %s", response)

            pressure = float(
                re.match(r"OK 00 ([\d\.E-]{7}) MBA.*", response.decode())[1]
            )

            logger.debug("Querying ion pump current at %s", self.ip.get())

            tn.write(COMMAND_CURRENT)
            response = tn.read_until(b">", 1)

            logger.debug("Response = %s", response)

            current = float(
                re.match(r"OK 00 ([\d\.E-]{7}) AMPS.*", response.decode())[1]
            )

            logger.debug(
                "Reporting pressure = %s, current = %s",
                pressure,
                current,
            )

            return CalibrationResult.OK, {
                "tags": {"sensor": self.description.get()},
                "fields": {"pressure": pressure, "current": current},
            }
