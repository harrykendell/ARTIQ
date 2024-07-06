import json
import logging
from pprint import pformat

import requests
from qbutler.calibration import Calibration
from qbutler.calibration import CalibrationResult

logger = logging.getLogger(__name__)

# API call details for weatherbit.io

# Note that this is a paid-for service, linked to Charles' personal account
# We're on the free tier and only get 500 calls per day. If you are reading this
# as an external user, please don't use this key! You'll stop our monitor from
# working and force me to think about key security :(
QUERY_URL = "https://api.weatherbit.io/v2.0/current"
API_KEY = "3096e39b1e984ee996eb2ffd3a8d2579"
QUERY_STR = {
    "lon": "-0.17901159470066544",
    "lat": "51.499391511681495",
    "units": "metric",
    "lang": "en",
    "key": API_KEY,
}


class MonitorWeather(Calibration):
    """
    MonitorWeather

    Query the temperature of a weather sensor near the Blackett lab
    """

    def build_calibration(self):
        self.set_timeout(int(24 * 60 * 60 / 50))

    @staticmethod
    def get_weather():
        response = requests.request("GET", QUERY_URL, params=QUERY_STR)

        if not response.ok:
            raise RuntimeError(
                f"API query failed with error code {response.status_code}"
            )

        parsed = json.loads(response.text)
        data = parsed["data"][0]

        logger.debug("Full weather report:")
        logger.debug(pformat(data))

        measurement_timestamp = data["ts"]

        return measurement_timestamp, {
            "solar_rad": float(data["solar_rad"]),
            "temperature": float(data["temp"]),
            "pressure": float(data["pres"]),
            "relative_humidity": int(data["rh"]),
        }

    def check_own_state(self):
        timestamp, weather_data = self.get_weather()
        return CalibrationResult.OK, weather_data
