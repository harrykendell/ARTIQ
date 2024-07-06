import logging

import requests
from qbutler.calibration import Calibration
from qbutler.calibration import CalibrationResult

logger = logging.getLogger(__name__)

# API call details for cronitor.io

# Note that this is a paid-for service, linked to Charles' personal account
# We're on the free tier. If you are reading this
# as an external user, please don't use this key! You'll stop our monitor from
# working and force me to think about key security which is boring :(
QUERY_URL = "https://cronitor.link/p/5de5a2d2d5b64e9b8711a630ca78dfcc/icl-artiq"


class MonitorHeartbeat(Calibration):
    """
    Heartbeat monitor

    Ping a monitor on Cronitor regularly - if this ping stops, we know the system went down
    """

    def build_calibration(self):
        self.set_timeout(3 * 60)

    @staticmethod
    def ping_cronitor():
        response = requests.request("GET", QUERY_URL)

        if not response.ok:
            raise RuntimeError(
                f"API query failed with error code {response.status_code}"
            )

    def check_own_state(self):
        self.ping_cronitor()
        return CalibrationResult.OK, None
