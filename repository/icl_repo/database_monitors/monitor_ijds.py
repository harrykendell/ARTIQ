import logging

from koheron_ctl200_laser_driver import CTL200
from qbutler.calibration import Calibration
from qbutler.calibration import CalibrationResult

AWAY_FROM_TEMPERATURE_SETPOINT_THRESHOLD = 0.05  # k

logger = logging.getLogger(__name__)


class _MonitorKoheron(Calibration):
    """
    Monitor for a Koheron CTL200 current controller, connected via USB

    Must be subclassed for the appropriate controller with `cls.controller_name`
    set to an entry in the device_db.
    """

    controller_name: str = None

    def __init__(self, *args, **kwargs):
        if self.controller_name is None:
            raise NotImplementedError(
                "You must subclass this interface class and set cls.controller_name"
            )

        super().__init__(*args, **kwargs)

    def build_calibration(self):
        self.controller: CTL200 = self.get_device(self.controller_name)
        self.set_timeout(10)

    def check_own_state(self):
        out = {}

        try:
            self.controller.ping()

            out["temperature_actual"] = (
                self.controller.get_temperature_actual() - 273.15
            )
            out["temperature_setpoint"] = (
                self.controller.get_temperature_setpoint() - 273.15
            )

            out["resistance_actual"] = self.controller.get_resistance_actual()
            out["resistance_setpoint"] = self.controller.get_resistance_setpoint()

            out["current"] = 1e-3 * self.controller.get_current_mA()
            out["voltage"] = self.controller.get_voltage()

            laser_is_on = self.controller.status()
            if not laser_is_on:
                out["status"] = "OFF"
                out["current"] = 0.0
            elif (
                abs(out["temperature_actual"] - out["temperature_setpoint"])
                > AWAY_FROM_TEMPERATURE_SETPOINT_THRESHOLD
            ):
                out["status"] = "SETTLING"
            else:
                out["status"] = "ON"

            result = (
                CalibrationResult.OK if out["status"] else CalibrationResult.BAD_DATA
            )

        except AttributeError:
            # The connection to the controller failed
            out["status"] = "ERROR"
            result = CalibrationResult.BAD_DATA

        return result, {
            "tags": {
                "device": self.controller_name,
                "parent": _MonitorKoheron.__name__,
            },
            "fields": out,
        }


class MonitorBlueIJD1(_MonitorKoheron):
    controller_name = "blue_IJD1_controller"


class MonitorBlueIJD2(_MonitorKoheron):
    controller_name = "blue_IJD2_controller"


class MonitorBlueIJD3(_MonitorKoheron):
    controller_name = "blue_IJD3_controller"


class MonitorRedIJD1(_MonitorKoheron):
    controller_name = "red_IJD1_controller"
