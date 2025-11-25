"""
Example KDC101_serial.py
Example Date of Creation: 2023-12-12
Example Date of Last Modification on Github: 2023-12-12
Version of Python used for Testing: 3.11.4
==================
Example Description: The example shows how to connect to KDC101 on Windows and Linux. The motor is homed and moved 1 mm
Tested with KDC101 and Z812
"""

"Go there to look for the protocols : https://www.thorlabs.com/software/apt/APT_Communications_Protocol_Rev_15.pdf"

import serial
import time
import numpy as np
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Starting KDC101 serial communication")

# total time program takes to run
start_time = time.time()

class KDC101:
    """
    Class for controlling Thorlabs KDC101 via serial communication
    max velocity = 2.4mm/s
    acceleration = 4.5mm/s^2
    """

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("KDC101 class initialized")

    enc_cnt = 34304  # encoder counts per rotation0.
    T = 2048 / (6 * 10**6)  # time constant
    home_position = 10  # in mm # home position in counts
    chan_ident = 1  # channel ID for KDC101

    def __init__(self, port="/dev/ttyUSB5", baudrate=115200, timeout=1):
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
            logger.debug(f"Serial port {port} opened for KDC101 communication")

    def mod_identify(self, sleep_time=1):
        """
        Identify the module.
        """
        command = bytearray([0x23, 0x02, 0x00, 0x00, 0x50, 0x01])
        self.ser.write(command)
        time.sleep(sleep_time)

    def Enable_channel_state(self, sleep_time=1):
        """
        Get the channel state.
        """
        command = bytearray([0x10, 0x02, 0x01, 0x01, 0xD0, 0x01])
        self.ser.write(command)
        time.sleep(sleep_time)

    def mot_move_stop(self):
        """
        Stop the motor move.
        """
        command = bytearray([0x65, 0x04, 0x01, 0x01, 0xD0, 0x01])
        self.ser.write(command)
        time.sleep(1)

    def read_channel_state(self):
        """
        Read the channel state.
        """
        command = bytearray([0x11, 0x02, 0x01, 0x00, 0xD0, 0x01])
        self.ser.write(command)
        time.sleep(1)
        response = self.ser.read_all()
        return response

    def set_pos_counter(self, position):
        """
        Set the position counter.
        """
        command = bytearray(
            [
                0x10,
                0x04,
                0x06,
                0x00,
                0xD0,
                0x01,
                0x01,
                0x00,
            ]
        )
        position_apt = self.get_position_apt(position)
        print(f"Position in APT counts: {position_apt}")
        position_bytes = position_apt.to_bytes(4, byteorder="little", signed=True)
        print(f"Position in APT counts in bytes: {position_bytes}")
        command.extend(position_bytes)
        self.ser.write(command)
        time.sleep(1)
        response = self.ser.read_all()
        return response

    def req_pos_counter(self):
        """
        Get the position counter.
        """
        command = bytearray([0x11, 0x04, 0x01, 0x00, 0xD0, 0x01])
        self.ser.write(command)
        response = self.ser.read_all()
        return response

    def error_response(self):
        """
        Read the error response.
        """
        command = bytearray([0x80, 0x00, 0x00, 0x00, 0xD0, 0x01])
        self.ser.write(command)
        time.sleep(1)
        response = self.ser.read_all()
        return response

    def return_bytes(self, value, length):
        """
        Return the byte representation of a value with specified length.
        """
        return value.to_bytes(length, byteorder="little", signed=True)

    def get_velocity_apt(self, velocity):  # velocity in mm/s
        vel_apt = round(self.enc_cnt * self.T * 65536 * velocity)
        return vel_apt

    def get_position_apt(self, position):  # position in mm
        pos_apt = round(self.enc_cnt * position)
        return pos_apt

    def get_acceleration_apt(
        self, acceleration
    ):  # acceleration in mm/s^2, return in the counts used by apt
        acc_apt = round(self.enc_cnt * (self.T**2) * 65536 * acceleration)
        return acc_apt

    def close(self):
        self.ser.close()

    def move_stage(self, position):
        """
        Move the stage to the specified position.
        """
        command = bytearray([0x48, 0x04, 0x06, 0x00, 0xD0, 0x01, 0x01, 0x00])
        command.extend(position.to_bytes(4, byteorder="little", signed=True))
        self.ser.write(command)
        self.ser.flushInput()
        self.ser.flushOutput()
        time.sleep(1)

    def set_rel_move_params(self, rel_distance):
        """
        Set the relative move parameters of the stage.
        """
        rel_distance_apt = self.get_position_apt(rel_distance)
        rel_distance_bytes = rel_distance_apt.to_bytes(
            4, byteorder="little", signed=True
        )
        command = bytearray(
            [
                0x45,
                0x04,
                0x06,
                0x00,
                0x50 | 0x80,
                0x01,
                0x01,
                0x00,
            ]
        )
        command.extend(rel_distance_bytes)
        self.ser.write(command)
        time.sleep(1)

    def set_abs_move_params(self, position, sleep_time=1):
        """
        Set the absolute move parameters of the stage.
        """
        #debugging for position limits
        if not (0 <= position <= 25.0):
            raise ValueError(
                "Position must be between 0 and 25.0mm, please check the stage limits MTS25/M-Z8"
            )
        position_apt = self.get_position_apt(position)
        position_bytes = position_apt.to_bytes(4, byteorder="little", signed=True)
        #check for valid position

        
        command = bytearray(
            [
                0x50,
                0x04,
                0x06,
                0x00,
                0x50 | 0x80,
                0x01,
                0x01,
                0x00,
            ]
        )
        command.extend(position_bytes)
        self.ser.write(command)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"setting stage to absolute position: {position} mm")
        time.sleep(sleep_time)

    def move_stage_absolute(self, sleep_time=1):
        """
        Move the stage to the absolute position.
        """
        command = bytearray([0x53, 0x04, 0x01, 0x00, 0x50, 0x01])
        self.ser.write(command)
        self.ser.flushInput()
        self.ser.flushOutput()
        time.sleep(sleep_time)

    def move_stage_relative(self, sleep_time=1):
        """
        Move the stage by a relative amount.
        """
        command = bytearray([0x48, 0x04, 0x01, 0x00, 0x50, 0x01])
        self.ser.write(command)
        self.ser.flushInput()
        self.ser.flushOutput()
        time.sleep(sleep_time)

    def set_home_params(self, home_dir, limit_switch, offset_distance, home_velocity):
        """
        Home the stage.
        home_dir: 0 , don't need direction for KDC101
        limit_switch: 0 , don't need limit switch for KDC101
        offset_distance: 0, don't need offset for KDC101
        home_velocity: velocity for homing (in mm/s) max 2.4 mm/s
        """
        if not (0 <= home_dir <= 1):
            raise ValueError("Home direction must be 0 or 1")
        if not (0 <= limit_switch <= 1):
            raise ValueError("Limit switch must be 0 or 1")
        if not (offset_distance == 0):
            raise ValueError("Offset distance must be 0")
        if not (0 <= home_velocity <= 2.4):
            raise ValueError("Home velocity must be between 0 and 2.4 mm/s")

        command = bytearray(
            [
                0x40,
                0x04,
                0x0E,
                0x00,
                0x50 | 0x80,
                0x01,
            ]
        )
        chan_ident_bytes = self.chan_ident.to_bytes(2, byteorder="little", signed=False)
        command.extend(chan_ident_bytes)
        home_dir = home_dir.to_bytes(2, byteorder="little", signed=False)
        command.extend(home_dir)
        limit_switch = limit_switch.to_bytes(2, byteorder="little", signed=False)
        command.extend(limit_switch)
        home_velocity = self.get_velocity_apt(2.0)  # in counts/s
        print(f"Home velocity in APT counts: {home_velocity}")
        home_velocity = home_velocity.to_bytes(4, byteorder="little", signed=False)
        command.extend(home_velocity)
        offset_distance = offset_distance.to_bytes(4, byteorder="little", signed=True)
        command.extend(offset_distance)

        self.ser.write(command)
        self.ser.flushInput()
        self.ser.flushOutput()
        time.sleep(1)

    def home_move_stage(self, sleep_time=1):
        """
        Home and move the stage to the home position.
        """
        command = bytearray([0x43, 0x04, 0x01, 0x00, 0x50, 0x01])
        self.ser.write(command)
        self.ser.flushInput()
        self.ser.flushOutput()
        time.sleep(sleep_time)

    def set_velocity_profile(self, min_velocity, acceleration, max_velocity, sleep_time=1):
        """
        Set the velocity profile of the stage.
        MAX velocity = 2.4 mm/s
        Acceleration = 4.5 mm/s^2
        MIN velocity = 0.0 mm/s
        PLEASE MAKE SURE THE VALUES ARE WITHIN THE LIMITS IT CAN HARM THE STAGE
        """
        if not (0 <= min_velocity <= 2.4):
            raise ValueError("Min velocity must be between 0 and 2.4 mm/s")
        if not (0 <= acceleration <= 4.5):
            raise ValueError("Acceleration must be between 0 and 4.5 mm/s^2")
        if not (0 <= max_velocity <= 2.4):
            raise ValueError("Max velocity must be between 0 and 2.4 mm/s")

        command = bytearray(
            [
                0x13,
                0x04,
                0x0E,
                0x00,
                0x50 | 0x80,
                0x01,
                0x01,
                0x00,
            ]
        )
        min_velocity = self.get_velocity_apt(min_velocity)
        acceleration = self.get_acceleration_apt(acceleration)
        max_velocity = self.get_velocity_apt(max_velocity)
        command.extend(min_velocity.to_bytes(4, byteorder="little", signed=True))
        command.extend(acceleration.to_bytes(4, byteorder="little", signed=True))
        command.extend(max_velocity.to_bytes(4, byteorder="little", signed=True))
        self.ser.write(command)
        time.sleep(sleep_time)

    def stop_motor(self):
        """
        Stop the motor.
        """
        command = bytearray([0x65, 0x04, 0x01, 0x01, 0x50, 0x01])
        self.ser.write(command)
        time.sleep(1)

    def set_trigger_mode(self):
        """
        Set the trigger mode.
        This parameter sets the trigger mode and move type to be
        initiated according to the numerical value entered in bits 0 to
        7 as follows
        Bit 0 (0x01): TRIGIN_ENABLE set to enable physical trigger
        input
        Bit 1 (0x02): TRIGOUT_ENABLE set to enable trigger output
        function (mode set by BIT2 or BIT3 below)
        Bit 2 (0x04): TRIGOUT_MODEFOLLOW set to enable physical
        trigger output to mirror trig in
        Bit 3 (0x08): TRIGOUT_MODEMOVEEND set to enable
        physical trigger output, remains active (high) until move end
        Bit 4 (0x10): TRIG_RELMOVE set for relative move on trigger
        Bit 5 (0x20): TRIG_ABSMOVE set for absolute move on trigger
        Bit 6 (0x40): TRIG_HOMEMOVE set for home sequence on trigger
        Bit 7 (0x80): TRIGOUT_NOTRIGIN set to enable physical
        trigger output with no physical trigger in (i.e. sw initiated
        trigger)

        """
        mode = 0x01 | 0x00 | 0x00 | 0x00 | 0x00 | 0x20 | 0x00 | 0x00 | 0x00
        # mode = 0x40  # set to trigger in enable only
        command = bytearray(
            [
                0x00,
                0x05,
                0x01, mode
            ]
        )
        
        command.extend([0x50, 0x01])
        self.ser.write(command)
        time.sleep(1)


#KDC101_device = KDC101(port="/dev/ttyUSB5", baudrate=115200, timeout=1)


#mode identify
#KDC101_device.mod_identify(sleep_time=0)
#trigger mode set
#KDC101_device.set_velocity_profile(min_velocity=0.0, acceleration=4.5, max_velocity=2.4, sleep_time=0)
#initialize_position = 20.0000
#KDC101_device.set_abs_move_params(initialize_position, sleep_time=1)
#KDC101_device.set_trigger_mode()

#for i in range(300):
#    KDC101_device.set_abs_move_params(initialize_position+0.001*i, sleep_time=0)
#    KDC101_device.move_stage_absolute(sleep_time=0)
    #logger.info(f"Moving to position: {initialize_position+0.001*i} mm")

#KDC101_device.set_home_params(
#   home_dir=0, limit_switch=0, offset_distance=0, home_velocity=0.5
##)
#KDC101_device.home_move_stage()
#time.sleep(1)  # wait for homing to complete
# print("Homing complete.")

# KDC101_device.set_rel_move_params(-5.0)
# KDC101_device.move_stage_relative()
# KDC101_device.close()


# set trigger mode to move on trigger input


# wait for trigger input





print("KDC101 example complete.")
