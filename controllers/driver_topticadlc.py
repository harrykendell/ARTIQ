from toptica.lasersdk.dlcpro.v3_2_0 import DLCpro
from toptica.lasersdk.dlcpro.v3_2_0 import Laser, DigifalcBoard
from toptica.lasersdk.dlcpro.v3_2_0 import NetworkConnection
import logging
import time

logger = logging.getLogger(__name__)


class TopticaDLCPro:
    """
    Thin wrapper for the Toptica SDK, to match the format that ARTIQ expects for initialisation

    To use this object, either use it in a context manager::

        driver = TopticaDLCPro(...)

        with driver:
            print(driver.get_laser().label.get())

    Or open a connection manually which you will close later::

        driver = TopticaDLCPro(...)

        driver.open()

        ...

        driver.close()
    """

    def __init__(self, *args, ip, laser=None, falc=None, simulation=False, rpc=False):
        if simulation:
            raise ValueError("Simulation mode is not supported for the Toptica SDK")

        if laser:
            assert laser in ["laser1", "laser2"], ValueError(
                f"Laser must be laser1 or laser2: got {laser}"
            )
        self.laser = laser

        if falc:
            assert falc in [1, 2, 3, 4], '"falc" must be 1, 2, 3 or 4'

        self.falc = falc
        self.ip = ip
        self._dlcpro = None

        if rpc:
            self.open()
            self.bring_methods_into_namespace()

    def bring_methods_into_namespace(self):
        # to work in RPCs we need all member variables to be accessible directly on this class as methods
        # so we hunt down the chain.

        """find all callables on the object
        - if its not a property add it to our class
        - if it is a property, check the type hint and if its a *Decop* type, add the .get and if available .set
        - otherwise recurse
        """
        from typing import get_type_hints

        def hunt_down(obj, path):

            for name in dir(obj):
                # skip private and special methods
                if name.startswith("_"):
                    continue

                attr = getattr(obj, name)

                # if its a Decop add its get/set and stop
                if "Mutable" in str(attr):
                    setattr(
                        self, f"{path}{name}_set", getattr(obj, name).set
                    )
                if "Decop" in str(attr):
                    setattr(self, f"{path}{name}", getattr(obj, name).get)
                    continue

                if "bound method" in str(attr):
                    setattr(self, f"{path}{name}", getattr(obj, name))
                    continue

                hunt_down(attr, f"{path}{name}_")

        hunt_down(self._dlcpro, "")

        print("methods added to namespace")

    def open(self):
        logger.debug("Opening connection to %s", self.ip)
        self.get_dlcpro().open()

    def close(self):
        logger.debug("Closing connection to %s", self.ip)
        self.get_dlcpro().close()

    def get_dlcpro(self) -> DLCpro:
        """Access the raw DLC Pro driver object

        Users should prefer to use the get_laser() function, so the details of
        which laser you're accessing can be stored in device_db"""

        if self._dlcpro is None:
            logger.debug("Making DLCPro driver for %s, %s", self.ip, self.laser)
            self._dlcpro = DLCpro(NetworkConnection(self.ip))

        return self._dlcpro

    def get_laser(self, laser=None) -> Laser:
        """Access the laser driver

        Returns either self.get_dlcpro().laser1 or self.get_dlcpro().laser2
        depending on which is stored in device_db
        """
        if not self.laser and not laser:
            raise ValueError("No laser specified during setup or as an argument")
        return getattr(self.get_dlcpro(), self.laser if self.laser else laser)

    def get_falc(self) -> DigifalcBoard:
        """Access the FALC associated with this laser if it exists

        Return the FALC configured during setup. To associate a falc with this
        laser, pass e.g. `falc = 1` during setup (or as part of your device_db
        if using ARTIQ).

        If this laser has no FALC associated with it, this function will raise a
        TypeError.
        """
        if not self.falc:
            raise TypeError("No falc specificied during setup")

        pro = self.get_dlcpro()

        if self.falc == 1:
            return pro.falc1
        elif self.falc == 2:
            return pro.falc2
        elif self.falc == 3:
            return pro.falc3
        elif self.falc == 4:
            return pro.falc4
        else:
            raise ValueError("Invalid FALC setting")

    def ping(self):
        """Check if the DLC Pro is reachable"""
        return self.get_dlcpro().system_label.get()

    # Pass on __enter__ and __exit__ so that users can use `with TopticaDLCPro`
    # to start a network connection
    def __enter__(self, *args, **kwargs):
        return self.get_dlcpro().__enter__(*args, **kwargs)

    def __exit__(self, *args, **kwargs):
        return self.get_dlcpro().__exit__(*args, **kwargs)
