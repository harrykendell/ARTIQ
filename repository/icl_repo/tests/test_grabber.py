from artiq.coredevice.core import Core
from artiq.coredevice.grabber import Grabber
from artiq.experiment import *
from artiq.experiment import delay
from artiq.language import ms
from artiq.language import now_mu
from artiq.language import us
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.result_channels import FloatChannel


class TestGrabber(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("grabber0")
        self.grabber0: Grabber

        self.setattr_device("ttl_camera_trigger_andor")

        self.setattr_argument(
            "timeout", NumberValue(default=1, precision=3, scale=1, step=1, unit="s")
        )

        self.setattr_argument(
            "roi_x1", NumberValue(default=1, precision=0, scale=1, step=1)
        )
        self.setattr_argument(
            "roi_x2", NumberValue(default=1, precision=0, scale=1, step=1)
        )
        self.setattr_argument(
            "roi_y1", NumberValue(default=1, precision=0, scale=1, step=1)
        )
        self.setattr_argument(
            "roi_y2", NumberValue(default=1, precision=0, scale=1, step=1)
        )

        self.setattr_result("sum", FloatChannel)
        self.sum: FloatChannel

    @kernel
    def run_once(self):
        self.core.reset()

        # Setup one grabber ROI
        self.grabber0.setup_roi(0, self.roi_x1, self.roi_y1, self.roi_x2, self.roi_y2)

        delay(10e-6)

        # Turn grabber ROI 0 on
        self.grabber0.gate_roi(0x01)

        # camera trigger
        self.ttl_camera_trigger_andor.pulse(10 * us)

        # get data
        data = [0]
        if self.timeout < 0.0:
            timeout_mu = -1
        else:
            timeout_mu = now_mu() + self.core.seconds_to_mu(self.timeout)
        self.grabber0.input_mu(data, timeout_mu=timeout_mu)

        # Disable the ROI again
        self.core.break_realtime()
        self.grabber0.gate_roi(0x00)

        self.core.reset()

        self.sum.push(data[0])


TestGrabber = make_fragment_scan_exp(TestGrabber)


class FrameGrabberExample(EnvExperiment):
    """
    FrameGrabberExample

    Copied from https://github.com/m-labs/artiq/issues/1369
    """

    def build(self):
        self.setattr_device("core")
        self.setattr_device("grabber0")
        self.setattr_device("ttl_camera_trigger_andor")

    @kernel
    def run(self):
        rois = [[227, 237, 237, 247], [247, 237, 257, 247]]
        mask = 0
        self.core.reset()
        for i in range(len(rois)):
            x0 = rois[i][0]
            y0 = rois[i][1]
            x1 = rois[i][2]
            y1 = rois[i][3]
            mask |= 1 << i
            self.grabber0.setup_roi(i, x0, y0, x1, y1)
        n = [0] * len(rois)

        self.ttl_camera_trigger_andor.pulse(10 * us)  # camera trigger
        delay(20 * ms)
        self.grabber0.gate_roi(mask)
        self.ttl_camera_trigger_andor.pulse(10 * us)  # camera trigger

        self.grabber0.input_mu(n)

        self.core.break_realtime()
        self.grabber0.gate_roi(0)

        print("ROI sums:", n)
        print("ROI mask:", mask)
