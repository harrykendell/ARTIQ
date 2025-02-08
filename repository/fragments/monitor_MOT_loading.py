import logging
import numpy as np

from artiq.coredevice.core import Core
from artiq.experiment import TFloat, TInt32, TInt64, TList
from artiq.experiment import kernel, rpc, delay_mu
from artiq.language.units import ms, s
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
from submodules.oitg.oitg.fitting import exponential_decay

from repository.fragments.read_adc import ReadSUServoADC
from repository.fragments.current_supply_setter import SetAnalogCurrentSupplies
from repository.models.devices import VDRIVEN_SUPPLIES

from device_db import server_addr

logger = logging.getLogger(__name__)


class MOTPhotodiodeMeasurement(Fragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_param(
            "current",
            FloatParam,
            "The current of the X1 coil when the MOT is active",
            default=VDRIVEN_SUPPLIES["X1"].default_current,
            min=0.0,
            max=2.0,
            unit="A",
        )
        self.current: FloatParamHandle

        self.setattr_fragment(
            "coil_setter",
            SetAnalogCurrentSupplies,
            [VDRIVEN_SUPPLIES["X1"]],
            init=False,
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
        self.coil_setter.turn_off()
        delay_mu(2 * initial_delay_mu)
        self.coil_setter.set_currents([self.current.get()])
        delay_mu(-initial_delay_mu)

        for i in range(num_points):
            data[i] = self.adc_reader.read_adc()
            delay_mu(delay_between_points_mu)


class MeasureMOTWithPDFrag(ExpFragment):
    """
    Plot the loading rate of the MOT by measuring the photodiode signal.
    """

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
            "total_loading_time",
            FloatParam,
            description="Total time to load the MOT",
            default=1 * s,
            unit="s",
            min=1 * ms,
            step=0.001,
        )
        self.total_loading_time: FloatParamHandle

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
            default=True,
        )
        self.zero_measurement: BoolParamHandle

        self.setattr_fragment("mot_measurer", MOTPhotodiodeMeasurement)
        self.mot_measurer: MOTPhotodiodeMeasurement

        self.setattr_param_rebind("current", self.mot_measurer)

        self.setattr_result("photodiode_voltage", OpaqueChannel)
        self.photodiode_voltage: OpaqueChannel

    @kernel
    def run_once(self):
        num_points = self.num_trace_points.get()

        trace_data = [0.0] * num_points

        self.core.break_realtime()
        self.mot_measurer.measure_MOT_fluorescence(
            num_points=num_points,
            delay_between_points_mu=self.core.seconds_to_mu(
                self.total_loading_time.get() / num_points
            ),
            initial_delay_mu=self.core.seconds_to_mu(self.initial_delay.get()),
            data=trace_data,
        )

        self.photodiode_voltage.push(np.array(trace_data))

        self.update_data(trace_data)

    def host_setup(self) -> None:
        super().host_setup()

    @rpc(flags={"async"})
    def update_data(self, data):
        self.name = f"MOT_loading.{self.scheduler.rid}"
        data = np.asarray(data)

        xs = np.linspace(0, self.total_loading_time.get(), self.num_trace_points.get())

        if self.zero_measurement.get():
            data -= data[0]

        try:
            fit_results, fit_errs, fit_xs, fit_ys = exponential_decay.fit(
                xs,
                data,
                evaluate_function=True,
                evaluate_n=self.num_trace_points.get(),
            )
        except Exception as e:
            logger.error(f"Error fitting MOT photodiode data: {e}")
            fit_results = {"tau": np.nan}
            fit_xs = xs
            fit_ys = np.zeros_like(data)

        for name, value in zip(("time", "voltage", "fit"), (fit_xs, data, fit_ys)):
            self.set_dataset(
                f"{self.name}.{name}",
                value,
                broadcast=True,
            )

        self.ccb.issue(
            "create_applet",
            "MOT Photodiode Voltage",
            f"${{artiq_applet}}plot_xy {self.name}.voltage --title 'tau = {fit_results['tau']: .3f}' --x {self.name}.time --fit {self.name}.fit --server {server_addr}",
        )


MOTImaging = make_fragment_scan_exp(MeasureMOTWithPDFrag)
