import logging
import pyvisa

logging.basicConfig(level=logging.WARNING)


class Agilent33600A:
    def __init__(
        self, ip_address: str = "192.168.0.7", timeout: int = 10000, silent=False
    ):
        """
        Initialize connection to the Agilent 33600A over LAN.
        :param ip_address: IP address of the AFG.
        """
        self.silent = silent
        self.rm = pyvisa.ResourceManager()
        if not silent:
            logging.info(f"Connecting to 33600A at {ip_address}")
        self.instrument = self.rm.open_resource(f"TCPIP::{ip_address}::INSTR")
        self.instrument.timeout = timeout  # Set timeout to 10 seconds

        if not silent:
            print(self.query("*IDN?"))

        # clear errors
        self.instrument.write("*CLS")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    # take a command and any arguments and send it to the AFG
    def write(self, command: str, *args):
        """Send a command to the AFG."""
        full_command = command + " " + " ".join(map(str, args))
        if not self.silent:
            logging.info(f"Writing: {full_command}")
        self.instrument.write(full_command)

        if logging.getLogger().isEnabledFor(logging.ERROR):
            error = self.instrument.query("*ESR?")
            if error != "+0\n":
                self.instrument.write("SYST:ERR?")
                logging.error(
                    f"Error: {error} for command: {full_command}\n{self.instrument.read()}"
                )

    def reset(self):
        """Reset the AFG."""
        if not self.silent:
            logging.info("Resetting 33600A")
        self.write("*RST")
        self.write("*CLS")

    def query(self, command: str):
        """Send a query to the AFG and return the response."""
        if not self.silent:
            logging.info(f"Querying: {command}")
        ret = self.instrument.query(command)
        if logging.getLogger().isEnabledFor(logging.ERROR):
            error = self.instrument.query("*ESR?")
            if error != "+0\n":
                logging.error(f"Error: {error} for command: {command}")
        return ret.strip()

    def format_freq(self, frequency):
        # we need this format +1.00E+05 with 2dp and alaways scientific notation
        return f"{frequency:+.2E}"

    def format_voltage(self, voltage):
        # we need this format +2.00 with sign and 2dp
        return f"{voltage:+.2f}"

    def sin_pulse(self, ch: int, frequency: float, voltage: float, periods: int):
        """Set the AFG to output a sine wave.
        ch: [1,2]
        frequency: Hz
        voltage: peak voltage
        periods: 1+
        """

        self.write(f"OUTPUT{ch}:LOAD 150")
        self.write(f"SOURCE{ch}:FUNCTION SIN")
        self.write(f"SOURCE{ch}:FREQUENCY {self.format_freq(frequency)}")
        self.write(f"SOURCE{ch}:VOLTAGE:HIGH {self.format_voltage(voltage)}")
        self.write(f"SOURCE{ch}:VOLTAGE:LOW {self.format_voltage(-voltage)}")

        self.write(f"SOURCE{ch}:BURST:MODE TRIGGERED")
        self.write(f"SOURCE{ch}:BURST:NCYCLES {periods}")
        self.write(f"SOURCE{ch}:BURST:STATE ON")
        self.write(f"TRIGGER{ch}:SOURCE EXTERNAL")

    def close(self):
        """Close the connection to the AFG."""
        if not self.silent:
            logging.info("Closing connection to 33600A")
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
        default="192.168.0.7",
        help="IP address of the AFG",
    )

    args = parser.parse_args()

    # Connect to the oscilloscope
    with Agilent33600A(ip_address=args.ip_address) as afg:
        # # Output a sine wave, and read a trace from channel 1
        afg.sin_pulse(1, 100, 2, 10)
