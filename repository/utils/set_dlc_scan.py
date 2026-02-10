# Author : Yolan Ankaine
# Date : Jan 2026

from sipyco.pc_rpc import Client
from driver_topticadlc_copy import TopticaDLCPro

from artiq.coredevice.core import Core
from artiq.experiment import EnumerationValue, kernel
from ndscan.experiment import BoolParam, ExpFragment
from ndscan.experiment.parameters import BoolParamHandle
from ndscan.experiment.entry_point import make_fragment_scan_exp
from repository.models.devices import VDrivenSupply

remote = Client("137.222.69.28", 3272, "TopticaDLCPro", timeout=1)


class SetDLC_Scan(ExpFragment):
    """
    Control the Relock scan on DLC Pro
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

        self.setattr_param("scan_enable", BoolParam, "Enable scan", default=False)
        self.scan_enable: BoolParamHandle

    # Disable the relock piezo scan on the Toptica DLC Pro
    def connect_to_DLC(self):
        with TopticaDLCPro(ip="192.168.0.4") as dlc:
            if dlc.laser1.scope.channel1.signal.get():
                if self.scan_enable.get():
                    # enable scan
                    dlc.laser1.scan.enabled.set(True)
                else:
                    # disable scam
                    dlc.laser1.scan.enabled.set(False)

    @kernel
    def run_once(self):
        """Disable the relock piezo scan on the Toptica DLC Pro"""

        self.core.reset()
        self.core.break_realtime()
        self.connect_to_DLC()


SetDLC_Scan = make_fragment_scan_exp(SetDLC_Scan)
