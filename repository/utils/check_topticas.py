from artiq.experiment import *
from artiq.coredevice.core import Core

from ndscan.experiment import *
from toptica.lasersdk.dlcpro.v3_2_0 import Laser

from submodules.topticadlcpro.toptica_wrapper.driver import TopticaDLCPro

import logging

class CheckTopticaFrag(ExpFragment):
    """
    LogTopticaLaser

    Logs the voltage, current, temperature of a Toptica DLCPro laser
    """

    def build_fragment(self, laser_name: str) -> None:
        self.laser_name = laser_name

        self.setattr_device("core")
        self.core: Core

        self.dlcpro: TopticaDLCPro = self.get_device(laser_name)

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

CheckToptica = make_fragment_scan_exp(CheckTopticaFrag)