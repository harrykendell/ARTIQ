import serial
import time
import logging
import math
import matplotlib.pyplot as plt


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Starting KDC101 serial communication")

# total time program takes to run
start_time = time.time()


class KIM101:
    """
    Class for controlling Thorlabs KIM101 via serial communication, for Piezo control for Mirrors for ODT
    """

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("KIM101 class initialized")

    enc_cnt = 34304  # encoder counts per rotation0.
    T = 2048 / (6 * 10**6)  # time constant
    home_position = 10  # in mm # home position in counts
    chan_ident = 1  # channel ID for KIM101

    def __init__(self, port="/dev/ttyUSB7", baudrate=115200, timeout=1):
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=1,
            xonxoff=0,
            rtscts=0,
            timeout=timeout,
        )
        self.ser.flushInput()
        self.ser.flushOutput()
        # time.sleep(0)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Serial port {port} opened for KIM101 communication")

    def mod_identify(self, sleep_time=1):
        """
        Identify the module.
        """
        command = bytearray([0x23, 0x02, 0x01, 0x00, 0x50, 0x01])
        self.ser.write(command)
        time.sleep(sleep_time)

    def current_position(self):
        """
        Get the current position of the mirror.
        """
        command = bytearray([0xC0, 0x08, 0x0E, 0x00, 0x50 , 0x01])
        self.ser.write(command)
        read_bytes = self.ser.read(6)
        print(read_bytes)
        position_counts = int.from_bytes(read_bytes[4:6], byteorder="little", signed=True)
        return position_counts

#KIM101 = KIM101()
#identify the module
#KIM101.mod_identify()
# Get current position
#current_pos = KIM101.current_position()
#logger.info(f"Current position: {current_pos} counts")