from artiq.experiment import EnvExperiment
from ndscan.experiment import ExpFragment
from ndscan.experiment import ResultChannel
from ndscan.experiment.entry_point import create_and_run_fragment_once
from ndscan.experiment.entry_point import make_fragment_scan_exp


class FooResultFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_result("foo")
        self.foo: ResultChannel

    def run_once(self):
        self.foo.push(123)


class FooResultExp(EnvExperiment):
    def run(self):
        results = create_and_run_fragment_once(self, FooResultFrag)
        print(results["foo"])


FooResultScan = make_fragment_scan_exp(FooResultFrag)
