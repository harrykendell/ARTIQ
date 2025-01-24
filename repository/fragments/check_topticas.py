from artiq.experiment import *
from artiq.coredevice.core import Core

from ndscan.experiment import *
from toptica.lasersdk.dlcpro.v3_2_0 import Laser

from submodules.topticadlcpro.toptica_wrapper.driver import TopticaDLCPro

import logging


class CheckTopticaFrag(ExpFragment):
    """
    CheckTopticaFrag

    Logs the voltage, current, temperature of a Toptica DLCPro laser
    """

    def build_fragment(self) -> None:

        self.setattr_device("core")
        self.core: Core

        self.setattr_argument(
            "laser_name",
            EnumerationValue(
                {"toptica_780", "toptica_852"},
                default="toptica_780",
            ),
        )
        self.laser_name: str

        self.dlcpro: TopticaDLCPro = self.get_device(self.laser_name)

    def host_setup(self):
        self.dlcpro.get_dlcpro().open()
        self.laser: Laser = self.dlcpro.get_laser()

        return super().host_setup()

    def host_cleanup(self):
        self.dlcpro.close()

        super().host_cleanup()

    def check_state(self):

        out = {}

        try:
            out["voltage_setpoint"] = self.laser.dl.pc.voltage_set.get()
            out["voltage_actual"] = self.laser.dl.pc.voltage_act.get()
            out["current_setpoint"] = self.laser.dl.cc.current_set.get()
            out["current_actual"] = self.laser.dl.cc.current_act.get()
            out["temperature_setpoint"] = self.laser.dl.tc.temp_set.get()
            out["temperature_actual"] = self.laser.dl.tc.temp_act.get()

        except AttributeError:
            # The connection to the controller failed
            out["status"] = "ERROR"

        logging.info(out)


CheckLaser = make_fragment_scan_exp(CheckTopticaFrag)
