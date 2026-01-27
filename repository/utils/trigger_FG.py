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
        # UI parameter: enable/disable trigger
        self.setattr_param(
            "enable",
            BoolParam,
            "Enable trigger?",
            default=True,
        )
        self.enable: BoolParamHandle

        # UI parameter: laser to re-lock

        self.setattr_param(
            "time_to_shift",
            FloatParam,
            "Delay for the laser to move",
            default=500 * ms,
            unit="ms",
        )
        self.time_to_shift: FloatParamHandle

        self.setattr_param(
            "reset", BoolParam, "Relock the laser instead", default=False
        )
        self.reset: BoolParamHandle

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

        # Unlock the laser
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

    # Disable the relock piezo scan on the Toptica DLC Pro
    def disable_relock_scan(self):
        with TopticaDLCPro(ip="192.168.0.4") as dlc:
            if dlc.laser1.scope.channel1.signal.get():
                dlc.laser1.scan.enabled.set(False)
                # delay(self.time_to_shift.get())  # delay for scan to disable
                # dlc.laser1.scan.enabled.set(True)

    @kernel
    def run_once(self):
        """- Trigger the Function Generator via TTL
        - Unlock the laser
        - Disable the relock piezo scan on the Toptica DLC Pro
        - Reset after modulation completed"""
        self.core.reset()

        # Ensure clean timing boundary
        self.core.break_realtime()

        self.unlock_ttl.output()
        self.ttl7.output()

        self.ttl7.off()
        delay(1 * us)  # wait for ttl to settle

        self.unlock_ttl.on()  # unlock laser
        self.ttl7.on()  # trigger FG
        delay(10 * ns)  # minimum pulse width (e.g. 10 ns).
        self.ttl7.off()

        delay(self.time_to_shift.get())  # wait for laser to shift
        self.setter.set_to_defaults()  # reset laser frequency
        self.unlock_ttl.off()  # relock laser

    def run(self):
        if not self.reset.get():
            self.disable_relock_scan()
            self.run_once()
            # logging.warning("%s left unlocked ", self.laser)


TriggerFuncGen = make_fragment_scan_exp(TriggerFuncGenFrag)
