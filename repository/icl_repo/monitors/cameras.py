from ndscan.experiment.entry_point import make_fragment_scan_exp

from icl_repo.lib.fragments.cameras.flir_camera import Chamber2HorizontalCamera
from icl_repo.lib.fragments.cameras.flir_camera import Chamber2VerticalCamera
from icl_repo.lib.fragments.cameras.flir_camera import MonitorCameraExp


class MonitorChamber2HorizCamera(MonitorCameraExp):
    camera_class = Chamber2HorizontalCamera


class MonitorChamber2VertCamera(MonitorCameraExp):
    camera_class = Chamber2VerticalCamera


MonitorChamber2HorizCamera = make_fragment_scan_exp(MonitorChamber2HorizCamera)  # type: ignore
MonitorChamber2VertCamera = make_fragment_scan_exp(MonitorChamber2VertCamera)  # type: ignore
