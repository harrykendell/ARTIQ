import logging
from copy import deepcopy

from artiq.language import PYONValue
from ndscan.experiment.entry_point import ArgumentInterface, make_fragment_scan_exp
from ndscan.utils import PARAMS_ARG_KEY

logger = logging.getLogger(__name__)

TOF_REPEATS_PER_POINT = 3


class _BenchmarkArgumentInterface(ArgumentInterface):
    """Apply experiment-owned ndscan defaults before persisted GUI state."""

    def build(self, fragments, default_scan):
        self._default_scan = default_scan
        super().build(fragments, scannable=True)

    def get_argument(self, key, processor, group=None, tooltip=None):
        if key == PARAMS_ARG_KEY:
            default_params = deepcopy(processor.default_value)
            default_params["scan"].update(deepcopy(self._default_scan))
            processor = PYONValue(default=default_params)
        return super().get_argument(key, processor, group, tooltip)


def make_benchmark_scan_exp(
    name,
    fragment_class,
):
    base_class = make_fragment_scan_exp(fragment_class)

    class _BenchmarkScan(base_class):
        def build(self):
            self.fragment = fragment_class(self, [])
            self.max_rtio_underflow_retries = 3
            self.max_transitory_error_retries = 10

            tof_times = getattr(fragment_class, "TOF_TIMES", None)
            default_scan = {}
            if tof_times is not None:
                default_scan = {
                    "axes": [
                        {
                            "type": "list",
                            "range": {
                                "values": list(tof_times),
                                "randomise_order": False,
                            },
                            "fqn": f"{self.fragment.fqn}.expansion_time",
                            "path": "*",
                        }
                    ],
                    "num_repeats": 1,
                    "num_repeats_per_point": TOF_REPEATS_PER_POINT,
                    "no_axes_mode": "single",
                    "randomise_order_globally": True,
                    "skip_on_persistent_transitory_error": False,
                }

            self.args = _BenchmarkArgumentInterface(
                self,
                [self.fragment],
                default_scan,
            )
            self.setattr_device("scheduler")

        def prepare(self):
            super().prepare()

    _BenchmarkScan.__name__ = name
    _BenchmarkScan.__qualname__ = name
    _BenchmarkScan.__doc__ = base_class.__doc__
    return _BenchmarkScan
