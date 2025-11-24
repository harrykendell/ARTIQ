import logging
from typing import List, Tuple

from numpy import int32, int64

from artiq.coredevice.core import Core
from artiq.coredevice.dma import CoreDMA
from artiq.coredevice.suservo import Channel as SUServoChannel
from artiq.experiment import TFloat, TInt32, kernel, portable
from artiq.language.core import at_mu, delay, delay_mu, now_mu
from artiq.language.units import MHz, ms, us
from ndscan.experiment import Fragment
from ndscan.experiment.parameters import FloatParam, FloatParamHandle, ParamHandle
from repository.fragments.eom_setter import EomFrag
from repository.fragments.supply_setter import SetSupplies
from repository.models import DEVICE, Eom, SUServoedBeam, VDrivenSupply
from repository.utils.dummy_devices import (
    DummyEom,
    DummyEomFrag,
    DummySetSupplies,
    DummySUServoChannel,
    DummySUServoedBeam,
    DummyVDrivenSupply,
)

logger = logging.getLogger(__name__)


class RampEvaporation(Fragment):
    """This class is specifically for the ramping the AOMs and Moving stages for lensing effect during evaporation."""
    
    def build_fragment(self,
        evaporation_aom_beams: List[SUServoedBeam],
        evaporation_stage_ttl: List[float],
        use_dummy_devices: bool = False,
    ):
        """
        Parameters
        ----------
        evaporation_aom_beams : List[SUServoedBeam]
            List of beams to be used for evaporation ramping.
        evaporation_stages : List[Tuple[float, float, float]]
            List of tuples containing (time in seconds, frequency in MHz, attenuation in dB)
            for each stage of the evaporation ramp.
        use_dummy_devices : bool
            Whether to use dummy devices for testing.
        """
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("core_dma")
        self.core_dma: CoreDMA

        # Set up evaporation AOM beams
        self.evaporation_beam_channels = []
        for beam in evaporation_aom_beams:
            if use_dummy_devices:
                channel = self.setattr_device(
                    f"dummy_evap_beam_{beam.name}",
                    DummySUServoedBeam,
                    beam,
                )
            else:
                channel = self.setattr_device(
                    f"evap_beam_{beam.name}",
                    SUServoedBeam[beam.name],
                )
            self.evaporation_beam_channels.append(channel)

        # Set up evaporation stage TTLs
        self.evaporation_stage_ttls = evaporation_stage_ttl
        if use_dummy_devices:
            self.evaporation_stage_ttls = [self.setattr_device("dummy_shutter")]

        # Validate inputs
        if not self.validate_AOM_channels():
            raise ValueError("Invalid AOM channels provided for evaporation.")
        if not self.validate_stage_ttls(self.evaporation_stage_ttls):
            raise ValueError("Invalid TTL values provided for evaporation stages.")

    def validate_AOM_channels(self):
        for channel in self.evaporation_beam_channels:
            if not isinstance(channel, SUServoChannel):
                logger.error(f"Invalid AOM channel: {channel}")
                return False
        return True
    
    def validate_stage_ttls(self, ttls: List[float]) -> bool:
        for ttl in ttls:
            if not isinstance(ttl, (float, int)):
                logger.error(f"Invalid TTL value: {ttl}")
                return False
        return True
    
    @kernel
    def device_setup(self) -> None:
        self.core.reset()
        self.core_dma.reset()
        for channel in self.evaporation_beam_channels:
            channel.setup()
        for ttl in self.evaporation_stage_ttls:
            ttl.setup()
        return super().device_setup()
