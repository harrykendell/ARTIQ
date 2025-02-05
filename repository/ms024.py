import time
import pyvisa
import numpy as np
import matplotlib.pyplot as plt
import logging

logging.basicConfig(level=logging.WARNING)


class MSO24:
    def __init__(self, ip_address: str = "192.168.0.5", timeout: int = 10000):
        """
        Initialize connection to the MSO24 oscilloscope over LAN.
        :param ip_address: IP address of the oscilloscope.
        """
        self.rm = pyvisa.ResourceManager()
        logging.info(f"Connecting to MSO24 at {ip_address}")
        self.instrument = self.rm.open_resource(f"TCPIP::{ip_address}::INSTR")
        self.instrument.timeout = timeout  # Set timeout to 10 seconds
        self.instrument.encoding = "latin_1"
        self.instrument.read_termination = "\n"
        self.instrument.write_termination = None
        self.reset()
        print(self.query("*IDN?"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # take a command and any arguments and send it to the oscilloscope
    def write(self, command: str, *args):
        """Send a command to the oscilloscope."""
        full_command = command + " " + " ".join(map(str, args))
        logging.info(f"Writing: {full_command}")
        self.instrument.write(full_command)

        if logging.getLogger().isEnabledFor(logging.ERROR):
            error = self.instrument.query("*ESR?")
            if error != "0":
                logging.error(f"Error: {error} for command: {full_command}")

    def reset(self):
        """Reset the oscilloscope."""
        logging.info("Resetting MSO24")
        self.write("*RST")
        self.write("*CLS")

    def query(self, command: str):
        """Send a query to the oscilloscope and return the response."""
        logging.info(f"Querying: {command}")
        ret = self.instrument.query(command)
        if logging.getLogger().isEnabledFor(logging.ERROR):
            error = self.instrument.query("*ESR?")
            if error != "0":
                logging.error(f"Error: {error} for command: {command}")
        return ret.strip()

    class AFGFunc:
        SINE = "SINE"
        SQUARE = "SQUARE"
        RAMP = "RAMP"
        PULSE = "PULSE"
        NOISE = "NOISE"
        DC = "DC"
        SINC = "SINC"
        GAUSSIAN = "GAUSSIAN"
        LORENTZ = "LORENTZ"
        EXPONENTIAL_RISE = "EXPONENTIAL_RISE"
        EXPONENTIAL_DECAY = "EXPONENTIAL_DECAY"

    def set_afg_output(self, waveform: AFGFunc, frequency: float, amplitude: float):
        """Set the Arbitrary Function Generator (AFG) output parameters."""
        self.write(f"AFG:FUNCtion {waveform}")
        self.write(f"AFG:FREQuency {frequency}")
        self.write(f"AFG:AMPLitude {amplitude}")
        self.write(f"AFG:OUTput:MODe CONTinuous")
        self.write("AFG:OUTput:STATE ON")

    def afg_sin(self, frequency: float, amplitude: float):
        """Set the AFG to output a sine wave."""
        self.set_afg_output(self.AFGFunc.SINE, frequency, amplitude)

    def set_timebase(self, scale: float):
        """Set the horizontal timebase scale."""
        self.write(f"HORizontal:MAIn:SCAle {scale}")

    def set_vertical_scale(self, channel: int, scale: float):
        """Set the vertical scale for a given channel."""
        self.write(f"CH{channel}:SCAle {scale}")

    def set_trigger(self, channel: int, level: float):
        """Set the trigger level for a given channel."""
        self.write(f"TRIGger:A:EDGE:SOUrce CH{channel}")
        self.write(f"TRIGger:A:EDGE:LEVel {level}")


    def get_trace(self, channel: int, trigger_channel: int):
        """Extract a trace from a channel based on another channel's trigger."""
        self.set_trigger(trigger_channel, 1.0)
        self.write("ACQuire:STATE ON")
        time.sleep(1)

        # Retrieve scaling factors
        tscale = float(self.query("WFMOutpre:XINCR?"))
        tstart = float(self.query("WFMOutpre:XZERO?"))
        vscale = float(self.query("WFMOutpre:YMULT?"))
        voff = float(self.query("WFMOutpre:YZERO?"))
        vpos = float(self.query("WFMOutpre:YOFF?"))
        att = float(self.query(f"CH{channel}:PROBEFunc:EXTAtten?"))

        # Configure data retrieval
        self.write("HEADER 0")
        self.write("DATA:ENCDG SRIBINARY")
        self.write(f"DATA:SOURCE CH{channel}")
        record = int(self.query("HORIZONTAL:RECORDLENGTH?"))
        logging.info(f"Record length: {record}")
        self.write(f"DATA:START 1")
        self.write(f"DATA:STOP {record}")
        self.write("WFMOutpre:BYT_N 1")
        self.write("ACQUIRE:STATE 0")  # Stop acquisition
        self.write("ACQUIRE:STOPAFTER SEQUENCE")
        self.write("ACQUIRE:STATE 1")  # Start acquisition
        self.query("*OPC?")  # Wait for operation complete

        # Retrieve binary waveform data
        bin_wave = self.instrument.query_binary_values(
            "CURVE?", datatype="b", container=np.array
        )

        # Scale data
        total_time = tscale * record
        tstop = tstart + total_time
        scaled_time = np.linspace(tstart, tstop, num=record, endpoint=False)
        scaled_wave = (bin_wave - vpos) * vscale / att + voff

        return scaled_time, scaled_wave

    def plot_trace(self, channel: int, trigger_channel: int):
        """Plot the trace from a channel with correct scaling."""
        time_axis, voltage_trace = self.get_trace(channel, trigger_channel)
        plt.figure()
        plt.plot(time_axis, voltage_trace, label=f"Channel {channel}")
        plt.xlabel("Time (s)")
        plt.ylabel("Voltage (V)")
        plt.title(f"Trace from Channel {channel}")
        plt.legend()
        plt.show()

    def close(self):
        """Close the connection to the oscilloscope."""
        logging.info("Closing connection to MSO24")
        self.instrument.close()
        self.rm.close()


if __name__ == "__main__":
    with MSO24() as mso24:
        mso24.afg_sin(1e6, 1)
        mso24.set_timebase(1e-6)
        mso24.set_vertical_scale(1, 1)
        mso24.plot_trace(1, 1)
