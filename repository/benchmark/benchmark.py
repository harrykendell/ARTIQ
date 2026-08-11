"""Benchmark experiments for the main MOT-to-ODT sequence."""

import logging

from artiq.language.units import ms, s

from repository.benchmark.common import make_benchmark_scan_exp
from repository.imaging.absorption_image import AbsorptionImageExpFrag

logger = logging.getLogger(__name__)

MOT_TOF_TIMES = tuple(value * ms for value in range(1, 7))
CMOT_TOF_TIMES = tuple(value * ms for value in range(5, 23, 2))
PGC_TOF_TIMES = tuple(value * ms for value in range(5, 31, 3))
ODT_TOF_TIMES = tuple(value * ms for value in range(1, 31, 3))
print(
    f"MOT: {len(MOT_TOF_TIMES)}, CMOT: {len(CMOT_TOF_TIMES)}, PGC: {len(PGC_TOF_TIMES)}, ODT {len(ODT_TOF_TIMES)}"
)

TOF_LOADING_TIME = 10 * s


class _TOFBenchmarkExpFrag(AbsorptionImageExpFrag):
    """Common absorption-image specialisation used by the TOF benchmarks."""

    DO_CMOT = False
    DO_PGC = False
    ODT_ACTIVE = False

    def build_fragment(self):
        super().build_fragment()

        self.override_param("do_cmot", self.DO_CMOT)
        self.override_param("do_pgc", self.DO_PGC)
        self.override_param("trap_frequency", False)
        self.override_param("ODT_active", self.ODT_ACTIVE)
        self.override_param("do_evaporation1", False)
        self.override_param("do_evaporation2", False)
        self.mot.override_param("loading_time", TOF_LOADING_TIME)


class MOTBenchFragment(_TOFBenchmarkExpFrag):
    """MOT"""

    DO_CMOT = False
    DO_PGC = False
    ODT_ACTIVE = False
    TOF_TIMES = MOT_TOF_TIMES


class CMOTBenchFragment(_TOFBenchmarkExpFrag):
    """CMOT"""

    DO_CMOT = True
    DO_PGC = False
    ODT_ACTIVE = False
    TOF_TIMES = CMOT_TOF_TIMES


class PGCBenchFragment(_TOFBenchmarkExpFrag):
    """PGC"""

    DO_CMOT = True
    DO_PGC = True
    ODT_ACTIVE = False
    TOF_TIMES = PGC_TOF_TIMES


class ODTBenchFragment(_TOFBenchmarkExpFrag):
    """ODT"""

    DO_CMOT = True
    DO_PGC = True
    ODT_ACTIVE = True
    TOF_TIMES = ODT_TOF_TIMES


MOTBench = make_benchmark_scan_exp(
    "MOTBench",
    MOTBenchFragment,
)
CMOTBench = make_benchmark_scan_exp(
    "CMOTBench",
    CMOTBenchFragment,
)
PGCBench = make_benchmark_scan_exp(
    "PGCBench",
    PGCBenchFragment,
)
ODTBench = make_benchmark_scan_exp(
    "ODTBench",
    ODTBenchFragment,
)
