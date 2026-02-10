## This code is written to add the external trigger to the Keysight Function Generator.
## It simulatenously unlocks the 852nm laser by turning off the servo while the FG is triggered.

# Author : Yolan Ankaine
# Date : Jan 2026



from sipyco.pc_rpc import Client
from driver_topticadlc_copy import TopticaDLCPro

from artiq.coredevice.core import Core
from artiq.coredevice.ttl import TTLInOut, TTLOut
from artiq.experiment import EnumerationValue, delay, kernel, ms, us, ns
from ndscan.experiment import BoolParam, ExpFragment, FloatParam
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.parameters import BoolParamHandle, FloatParamHandle
from repository.fragments.supply_setter import SetSupplies
from repository.models.devices import VDrivenSupply
from repository.utils.get_local_devices import get_local_devices

remote = Client("137.222.69.28", 3272, "TopticaDLCPro", timeout=1)


class TriggerFuncGenFrag(ExpFragment):
    """
    Trigger a function generator via TTL
    Unlock a laser while triggering
    Disable the Relock scan on DLC Pro
    """

    def build_fragment(self):

        # Devices
        self.setattr_device("core")
        self.core: Core

        # Retrieve the laser to be modulated (default = 852 nm ECDL)
        lasers = [dev.name for dev in VDrivenSupply.values() if dev.unit == "MHz"]
        default = lasers[1]
        self.setattr_argument("laser", EnumerationValue(lasers, default=default))
        self.laser: str
        self.setattr_device("core")
        self.core: Core

        if self.laser is not None:
            current_config = VDrivenSupply[self.laser]
        else:
            current_config = VDrivenSupply[default]

        self.setattr_fragment("setter", SetSupplies, [current_config], init=False)
        self.setter: SetSupplies

        # Define TTL channels

        # Laser unlock TTL
        unlocks = [dev for dev in get_local_devices(self, TTLInOut) if "unlock" in dev]
        default = unlocks[0]
        self.setattr_argument("ttl", EnumerationValue(unlocks))  # ttl 6
        self.ttl: str

        if self.ttl is not None:
            self.unlock_ttl: TTLInOut = self.get_device(self.ttl)
        else:
            self.unlock_ttl: TTLInOut = self.get_device(default)

        # Function Generator trigger TTL
        self.setattr_device("ttl7")
        self.ttl7: TTLOut

        # UI parameter : Laser Lock/Unlock
        self.setattr_param("reset", BoolParam, "Lock the laser?", default=False)
        self.reset: BoolParamHandle

        # UI parameter : laser settling time

        self.setattr_param(
            "time_to_shift",
            FloatParam,
            "Delay for the laser to move",
            default=500 * ms,
            unit="ms",
        )
        self.time_to_shift: FloatParamHandle

        # UI parameter : Enable/Disable the relock scan
        self.setattr_param(
            "scan_enable",
            BoolParam,
            "Enable relock scan?",
            default=False,
        )
        self.scan_enable: BoolParamHandle

        # UI parameter : Enable/Disable trigger
        self.setattr_param(
            "enable_trig",
            BoolParam,
            "Enable trigger?",
            default=True,
        )
        self.enable: BoolParamHandle

    # ----- Experiment functions -----#

    # -------------------- Version 1 --------------------------------
    # # Lock or Unlock a TOPTICA ECDL
    # def lock_unlock_laser(self):
    #     if self.reset.get():
    #         """
    #         Relock an ECDL.
    #         Then after `time_to_shift` seconds, turn the TTL off
    #         """
    #         self.setter.set_to_defaults()
    #         delay(self.time_to_shift.get())
    #         self.unlock_ttl.off()
    #         logging.warning("Locking %s", self.laser)

    #     else:
    #         """
    #         Unlock an ECDL
    #         """
    #         self.unlock_ttl.on()
    #         logging.warning("Unlocking %s", self.laser)

    # # Disable the relock piezo scan on the Toptica DLC Pro
    # def connect_to_DLC(self):
    #     with TopticaDLCPro(ip="192.168.0.4") as dlc:
    #         if dlc.laser1.scope.channel1.signal.get():
    #             if self.scan_enable.get():
    #                 """Enable scan"""
    #                 dlc.laser1.scan.enabled.set(True)
    #             else:
    #                 """Disable scan"""
    #                 dlc.laser1.scan.enabled.set(False)

    # # Trigger the function generator
    # def trigger_FG(self):
    #     """Trigger the function generator via TTL"""

    # if self.enable_trig.get():
    #     self.ttl7.output()  # ensure ttl is output
    #     self.ttl7.off()  # ensure ttl is low

    #     delay(1 * us)  # wait for ttl to settle
    #     self.ttl7.on()  # trigger FG
    #     delay(10 * ns)  # minimum pulse width (e.g. 10 ns)

    #     self.ttl7.off()  # turn off the ttl

    # # Perform the experiment once
    # @kernel
    # def run_once(self):
    #     """
    #     - Unlock the laser
    #     - Disable the relock piezo scan on the Toptica DLC Pro
    #     - Trigger the Function Generator via TTL
    #     """
    #     # Reset the core  and break realtime to ensure clean timing boundary
    #     self.core.reset()
    #     self.core.break_realtime()

    #     # Experiment sequence
    #     #self.lock_unlock_laser()  # lock or unlock
    #     self.connect_to_DLC()  # disable or enable scan on DLC Pro
    #     self.trigger_FG()  # trigger the function generator

    # -------------------- Version 2 --------------------------------
    # Disable the relock piezo scan on the Toptica DLC Pro
    def connect_to_DLC(self):
        with TopticaDLCPro(ip="192.168.0.4") as dlc:
            if dlc.laser1.scope.channel1.signal.get():
                if self.scan_enable.get():
                    """Enable scan"""
                    dlc.laser1.scan.enabled.set(True)
                else:
                    """Disable scan"""
                    dlc.laser1.scan.enabled.set(False)

    # def run(self):
    #     self.connect_to_DLC()
    #     self.run_once()

    @kernel
    def run_once(self):
        """
        - Unlock the laser
        - Disable the relock piezo scan on the Toptica DLC Pro
        - Trigger the Function Generator via TTL
        """

        # Reset the core  and break realtime to ensure clean timing boundary
        self.core.reset()
        self.core.break_realtime()

        # ----- Experiment sequence -----#
        # # 1. Unlock the laser
        # self.unlock_ttl.output()

        # # 2. Disable scan
        self.connect_to_DLC()

        # Reset the core  and break realtime to ensure clean timing boundary
        self.core.reset()
        self.core.break_realtime()

        # 3. Trigger the function generator
        # self.trigger_FG()  # trigger the function generator

        if self.enable_trig.get():
            self.ttl7.output()  # ensure ttl is output
            self.ttl7.off()  # ensure ttl is low

            delay(1 * us)  # wait for ttl to settle
            self.ttl7.on()  # trigger FG
            delay(10 * ns)  # minimum pulse width (e.g. 10 ns)

            self.ttl7.off()  # turn off the ttl


TriggerFuncGen = make_fragment_scan_exp(TriggerFuncGenFrag)
