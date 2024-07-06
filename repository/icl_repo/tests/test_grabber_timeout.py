import logging

from artiq.coredevice.core import Core
from artiq.coredevice.grabber import Grabber
from artiq.coredevice.grabber import OutOfSyncException
from artiq.coredevice.rtio import rtio_input_data
from artiq.coredevice.rtio import rtio_input_timestamped_data
from artiq.experiment import *
from artiq.experiment import delay
from artiq.experiment import now_mu
from artiq.language import us
from ndscan.experiment import ExpFragment
from ndscan.experiment.entry_point import make_fragment_scan_exp
from ndscan.experiment.result_channels import FloatChannel
from numpy import int64

logger = logging.getLogger(__name__)


class TestGrabberTimeoutFrag(ExpFragment):
    def build_fragment(self):
        self.setattr_device("core")
        self.core: Core

        self.setattr_device("grabber0")
        self.grabber0: Grabber

        self.setattr_device("ttl_camera_trigger_andor")

        self.setattr_argument(
            "timeout", NumberValue(default=100, precision=0, scale=1, step=1, unit="s")
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

        self.setattr_result("timestamp", FloatChannel, display_hints={"priority": -1})
        self.timestamp: FloatChannel

    @kernel
    def input_timeout_mu(self, grabber, data, timeout_mu: TInt64):
        """
        Retrieves the accumulated values for one frame from the ROI engines.
        Blocks until values are available.

        The input list must be a list of integers of the same length as there
        are enabled ROI engines. This method replaces the elements of the
        input list with the outputs of the enabled ROI engines, sorted by
        number.

        If the number of elements in the list does not match the number of
        ROI engines that produced output, an exception will be raised during
        this call or the next.
        """
        channel = grabber.channel_base + 1

        logger.info("Getting sentinel")

        timestamp, sentinel = rtio_input_timestamped_data(timeout_mu, channel)

        logger.info("Timestamp = %s, sentinel = %s", timestamp, sentinel)

        if timestamp == -1:
            raise RuntimeError("Timeout before Grabber frame available")

        if sentinel != grabber.sentinel:
            raise OutOfSyncException

        timestamp = -1

        logger.info("Getting input data")

        for i in range(len(data)):
            timestamp, roi_output = rtio_input_timestamped_data(timeout_mu, channel)
            if timestamp == -1:
                raise RuntimeError("Timeout reached")
            if roi_output == grabber.sentinel:
                raise OutOfSyncException
            data[i] = roi_output

        return timestamp

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
        timestamp = self.input_timeout_mu(
            self.grabber0, data, now_mu() + self.core.seconds_to_mu(self.timeout)
        )

        # Disable the ROI again
        self.core.break_realtime()
        self.grabber0.gate_roi(0x00)

        self.core.reset()

        self.sum.push(data[0])
        self.timestamp.push(timestamp)


TestGrabberTimeout = make_fragment_scan_exp(TestGrabberTimeoutFrag)
