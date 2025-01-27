import logging
import numpy as np

from artiq.coredevice.core import Core
from artiq.experiment import TFloat, TInt32, TInt64, TList
from artiq.experiment import kernel, rpc, delay_mu
from artiq.language.units import ms
from ndscan.experiment import (
    Fragment,
    ExpFragment,
    FloatChannel,
    OpaqueChannel,
    FloatParam,
    IntParam,
    BoolParam,
)
from ndscan.experiment.parameters import (
    FloatParamHandle,
    IntParamHandle,
    BoolParamHandle,
)
from ndscan.experiment.entry_point import make_fragment_scan_exp

from repository.fragments.read_adc import ReadSUServoADC
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.models.devices import VDRIVEN_SUPPLIES

logger = logging.getLogger(__name__)


class MOTPhotodiodeMeasurement(Fragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_param(
            "current",
            FloatParam,
            "The current of the X1 coil when the MOT is active",
            default=1.0,
            min=0.0,
            max=2.0,
        )
        self.current: FloatParamHandle

        self.setattr_fragment(
            "coil_setter", SetAnalogCurrentSupplies, VDRIVEN_SUPPLIES["X1"]
        )
        self.coil_setter: SetAnalogCurrentSupplies

        photodiode_suservo_channel = "MOT_photodiode"

        # Load the ADC utility subfragment
        self.setattr_fragment(
            "adc_reader",
            ReadSUServoADC,
            self.get_device(photodiode_suservo_channel),
        )
        self.adc_reader: ReadSUServoADC

    @kernel
    def measure_MOT_fluorescence(
        self,
        num_points: TInt32,
        delay_between_points_mu: TInt64,
        initial_delay_mu: TInt64,
        data: TList(TFloat),
    ) -> None:
        """
        Read the fluorescence out into an array.

        You must pass an array of floats with size <num_points> to `data`.
        """
        self.core.break_realtime()
        self.coil_setter.set_currents(0.0)
        delay_mu(initial_delay_mu)
        self.coil_setter.set_currents(self.current.get())

        for i in range(num_points):
            data[i] = self.adc_reader.read_adc()
            delay_mu(delay_between_points_mu)


class MeasureMOTWithPDFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("ccb")
        self.setattr_device("scheduler")

        self.setattr_param(
            "initial_delay",
            FloatParam,
            description="Delay between closing shutter and starting loading the MOT",
            default=100 * ms,
            unit="ms",
            min=1 * ms,
            step=1,
        )

        self.setattr_param(
            "delay_between_trace_points",
            FloatParam,
            description="Delay between points in the photodiode trace",
            default=1 * ms,
            unit="ms",
            min=1 * ms,
            step=1,
        )
        self.delay_between_trace_points: FloatParamHandle

        self.setattr_param(
            "num_trace_points",
            IntParam,
            description="Number of points in the photodiode trace",
            default=1000,
            min=1,
        )
        self.num_trace_points: IntParamHandle

        self.setattr_param(
            "zero_measurement",
            BoolParam,
            description="Remove the zero time amplitude from the values",
            default=False,
        )
        self.zero_measurement: BoolParamHandle

        self.setattr_fragment("mot_measurer", MOTPhotodiodeMeasurement)
        self.mot_measurer: MOTPhotodiodeMeasurement

        self.setattr_result("photodiode_voltage", OpaqueChannel)
        self.photodiode_voltage: OpaqueChannel

    @kernel
    def run_once(self):
        num_points = self.num_trace_points.get()

        trace_data = [0.0] * num_points

        self.mot_measurer.measure_MOT_fluorescence(
            num_points=num_points,
            delay_between_points_mu=self.core.seconds_to_mu(
                self.delay_between_trace_points.get()
            ),
            initial_delay_mu=self.core.seconds_to_mu(self.initial_delay.get()),
            data=trace_data,
        )

        self.photodiode_voltage.push(np.array(trace_data))

        if self.zero_measurement:
            trace_data -= [trace_data[0]] * num_points

        self.update_data(trace_data)

    def host_setup(self) -> None:
        super().host_setup()
        self.name = f"MOT_loading.{self.scheduler.rid}"
        self.set_dataset(
            self.name,
            0.0,
            broadcast=True,
        )

    @rpc
    def update_data(self, data):
        self.name = f"MOT_loading.{self.scheduler.rid}"
        self.set_dataset(
            self.name,
            data,
            broadcast=True,
            persist=True,
            archive=True,
        )

        self.ccb.issue(
            "create_applet",
            "MOT Photodiode Voltage",
            f"${{artiq_applet}}plot_xy {self.name}",
        )


MOTImaging = make_fragment_scan_exp(MeasureMOTWithPDFrag)
