from ndscan.experiment import *

from icl_repo.lib.fragments.beams.reset_all_beams import ResetAllICLBeams


class ResetBeamsFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.setattr_fragment("reset", ResetAllICLBeams)

    @kernel
    def run_once(self) -> None:
        print("Running...")


ResetBeams = make_fragment_scan_exp(ResetBeamsFrag)
