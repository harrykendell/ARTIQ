from artiq.coredevice.core import Core
from ndscan.experiment import ExpFragment
from ndscan.experiment import FloatChannel
from ndscan.experiment import kernel
from ndscan.experiment import make_fragment_scan_exp

from repository.fragments.read_adc import ReadSamplerADC


class ReadSamplerFrag(ExpFragment):
    """
    Take a reading from a sampler
    """

    def build_fragment(self) -> None:
        self.core: Core = self.get_device("core")

        self.setattr_fragment("sampler_reader", ReadSamplerADC)
        self.sampler_reader: ReadSamplerADC

        self.setattr_param_rebind("sampler_channel_number", self.sampler_reader)

        self.setattr_result("reading", FloatChannel)
        self.reading: FloatChannel

    @kernel
    def run_once(self) -> None:
        self.core.break_realtime()
        measurement = self.sampler_reader.read_adc()
        self.reading.push(measurement)


ReadSampler = make_fragment_scan_exp(ReadSamplerFrag)
