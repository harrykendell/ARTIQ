from artiq.coredevice.core import Core
from artiq.experiment import delay
from artiq.experiment import now_mu
from ndscan.experiment import ExpFragment
from ndscan.experiment import kernel
from ndscan.experiment.entry_point import make_fragment_scan_exp

from icl_repo.lib.fragments.blue_3d_mot import Blue3DMOTFrag


class TestLoadBlueMOT(ExpFragment):
    def build_fragment(self) -> None:
        self.setattr_device("core")
        self.core: Core

        self.setattr_fragment("blue_mot_controller", Blue3DMOTFrag)
        self.blue_mot_controller: Blue3DMOTFrag

    @kernel
    def run_once(self):
        self.core.break_realtime()
        self.blue_mot_controller.load_mot(clearout=True)


TestLoadBlueMOT = make_fragment_scan_exp(TestLoadBlueMOT)
