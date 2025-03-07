import time
import pyvisa
import numpy as np
import matplotlib.pyplot as plt
import logging

logging.basicConfig(level=logging.WARNING)


def assert_near(a, b, tol=1e-9):
    assert np.all(np.abs(a - b) < tol)


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
        # self.reset()
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

    def set_volt_scale(self, channel: int, scale: float):
        """Set the vertical scale for a given channel."""
        self.write(f"CH{channel}:SCAle {scale}")

    def set_trigger(self, channel: int, level: float):
        """Set the trigger level for a given channel."""
        self.write(f"TRIGger:A:EDGE:SOUrce CH{channel}")
        self.write(f"TRIGger:A:LEVel:CH{channel} {level}")

    def set_averaging(self, num_avg: int = 1):
        """Set the number of averages for the acquisition."""
        self.write("ACQUIRE:STOPAFTER SEQUENCE")
        self.write(f"ACQUIRE:NUMAVG {num_avg}")
        self.write("ACQUIRE:MODE AVERAGE")

    def get_trace(self, channels: int | list[int]):
        """Extract traces from the given channels."""

        if isinstance(channels, int):
            channels = [channels]

        self.write("ACQUIRE:STATE 0")  # Stop acquisition
        self.write("ACQUIRE:STOPAFTER SEQUENCE")
        self.write("ACQUIRE:STATE 1")  # Start acquisition
        self.query("*OPC?")  # Wait for aquisition to complete

        # Configure data retrieval
        self.write("HEADER 0")
        self.write("DATA:ENCDG SRIBINARY")

        # Retrieve binary waveform data
        waves = dict()

        chs = self.query("DATA:SOURCE:AVAILABLE?").split(",")
        for ch in channels:
            if f"CH{ch}" not in chs:
                logging.warning(
                    f"CH{ch} not available for data retrieval (available: {chs})"
                )
                continue

            self.write(f"DATA:SOURCE CH{ch}")

            self.write(f"DATA:START 1")
            record = int(self.query("HORIZONTAL:RECORDLENGTH?"))
            self.write(f"DATA:STOP {record}")
            self.write("WFMOutpre:BYT_N 1")
            self.query("*OPC?")  # Wait for operation complete
            bin_wave = self.instrument.query_binary_values(
                "CURVE?", datatype="b", container=np.array
            )

            # Retrieve scaling factors
            vscale = float(self.query("WFMOutpre:YMULT?"))
            voff = float(self.query("WFMOutpre:YZERO?"))
            vpos = float(self.query("WFMOutpre:YOFF?"))
            att = float(self.query(f"CH{ch}:PROBEFunc:EXTAtten?"))
            # Scale data
            waves[ch] = (bin_wave - vpos) * vscale / att + voff

        tscale = float(self.query("WFMOutpre:XINCR?"))
        tstart = float(self.query("WFMOutpre:XZERO?"))
        total_time = tscale * record
        tstop = tstart + total_time
        time = np.linspace(tstart, tstop, num=record, endpoint=False)

        return time, waves

    def plot_trace(self, time_axis, voltage_trace, channel: int = 1):
        """Basic plot of a trace from a channel."""
        plt.figure()
        plt.plot(time_axis, voltage_trace, label=f"Channel {channel}")
        plt.xlabel("Time (s)")
        plt.ylabel("Voltage (V)")
        plt.title(f"Trace from Channel {channel}")
        plt.legend()
        plt.show()

    def save_trace_to_file(self, time_axis, voltage_trace, filename: str = "trace.csv"):
        """Save the trace to a file."""
        # if theres no filetype, add .csv
        if "." not in filename:
            filename = filename + ".csv"

        with open(filename, "w") as f:
            f.write("Time (s),Voltage (V)\n")
            for t, v in zip(time_axis, voltage_trace):
                f.write(f"{t},{v}\n")

    def save_traces_to_file(
        self,
        time: np.ndarray,
        voltage_traces: dict[int, np.ndarray],
        filename: str = "traces.csv",
    ):
        """Save multiple traces to a file."""
        if "." not in filename:
            filename = filename + ".csv"

        with open(filename, "w") as f:
            f.write("Time (s)")
            for i in voltage_traces.keys():
                f.write(f",Ch{i} (V)")
            f.write("\n")

            for t, vs in zip(time, zip(*voltage_traces.values())):
                f.write(f"{t}")
                for v in vs:
                    f.write(f",{v}")
                f.write("\n")

    def close(self):
        """Close the connection to the oscilloscope."""
        logging.info("Closing connection to MSO24")
        self.instrument.close()
        self.rm.close()


if __name__ == "__main__":
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-ip",
        "--ip_address",
        type=str,
        default="192.168.0.5",
        help="IP address of the oscilloscope",
    )

    parser.add_argument(
        "-c",
        "--channel",
        type=int,
        default=1,
        help="Channel number to read from",
    )

    parser.add_argument(
        "-o",
        "--output_file",
        type=str,
        default="trace.csv",
        help="Output file to save the trace",
    )
    args = parser.parse_args()

    # Connect to the oscilloscope
    with MSO24(ip_address=args.ip_address) as ms024:

        # # Output a sine wave, and read a trace from channel 1
        # ms024.afg_sin(1e6, 1)
        # ms024.set_timebase(1e-6)
        # ms024.set_volt_scale(1, 1)
        # ms024.set_trigger(1, 0)

        ms024.set_averaging(50)
        ts, vs = ms024.get_trace([1, 3])
        plt.plot(ts, vs[1], label="Channel 1")
        plt.plot(ts, vs[3], label="Channel 3")
        plt.show()

        ms024.save_traces_to_file(ts, vs, filename=args.output_file)
        print(f"Trace saved to {args.output_file}")
