"""
Tektronix MSO24 Driver
Tested with:
TCPIP0::<ip>::inst0::INSTR
 
Requires:
    pip install pyvisa
"""
 
from pathlib import Path
from datetime import datetime
import pyvisa
 
 
class MSO24:
    def __init__(self, ip, timeout=30000, save_dir=None):
 
        self.ip = ip
        self.timeout = timeout
 
        self.rm = None
        self.scope = None
 
        if save_dir is None:
            save_dir = Path.home()
 
        self.save_dir = Path(save_dir)
 
    # =====================================================
    # Connection
    # =====================================================
 
    def connect(self):
 
        self.rm = pyvisa.ResourceManager()
 
        self.scope = self.rm.open_resource(f"TCPIP0::{self.ip}::inst0::INSTR")
 
        self.scope.timeout = self.timeout
 
        return self.idn()
 
    def close(self):
 
        if self.scope:
            self.scope.close()
 
    def idn(self):
        return self.query("*IDN?")
 
    # =====================================================
    # Raw SCPI
    # =====================================================
 
    def write(self, cmd):
        return self.scope.write(cmd)
 
    def query(self, cmd):
        return self.scope.query(cmd).strip()
 
    def query_float(self, cmd):
        return float(self.query(cmd))
 
    def query_int(self, cmd):
        return int(float(self.query(cmd)))
 
    def wait_opc(self):
        return self.query("*OPC?")
 
    def reset(self):
        self.write("*RST")
 
    def clear_status(self):
        self.write("*CLS")
 
    # =====================================================
    # Acquisition
    # =====================================================
 
    def run(self):
        self.write("ACQuire:STATE RUN")
 
    def stop(self):
        self.write("ACQuire:STATE STOP")
 
    def single(self):
        self.write("ACQuire:STOPAfter SEQUENCE")
        self.write("ACQuire:STATE RUN")
 
    def autoset(self):
        self.write("AUTOSet EXECute")
 
    def force_trigger(self):
        self.write("TRIGger FORCe")
 
    # =====================================================
    # Channels
    # =====================================================
 
    def channel_on(self, ch):
        self.write(f"SELect:CH{ch} ON")
 
    def channel_off(self, ch):
        self.write(f"SELect:CH{ch} OFF")
 
    def channel_state(self, ch):
        return self.query(f"SELect:CH{ch}?")
 
    def get_ch_scale(self, ch):
        return self.query_float(f"CH{ch}:SCAle?")
 
    def set_ch_scale(self, ch, value):
        self.write(f"CH{ch}:SCAle {value}")
 
    def get_ch_offset(self, ch):
        return self.query_float(f"CH{ch}:OFFSet?")
 
    def set_ch_offset(self, ch, value):
        self.write(f"CH{ch}:OFFSet {value}")
 
    # =====================================================
    # Horizontal
    # =====================================================
 
    def get_timebase(self):
        return self.query_float("HORizontal:SCAle?")
 
    def set_timebase(self, value):
        self.write(f"HORizontal:SCAle {value}")
 
    # =====================================================
    # Trigger
    # =====================================================
 
    def get_trigger_level(self):
        return self.query_float("TRIGger:A:LEVel?")
 
    def set_trigger_level(self, value):
        self.write(f"TRIGger:A:LEVel {value}")
 
    # =====================================================
    # Files
    # =====================================================
 
    def read_file(self, remote_file):
 
        self.write(f'FILESystem:READFile "{remote_file}"')
 
        return self.scope.read_raw()
 
    def delete_file(self, remote_file):
 
        self.write(f'FILESystem:DELEte "{remote_file}"')
 
    def list_files(self):
        return self.query("FILESystem:DIR?")
 
    # =====================================================
    # Helpers
    # =====================================================
 
    def _timestamp(self):
 
        return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
 
    # =====================================================
    # Screenshot
    # =====================================================
 
    def screenshot(self, filename=None):
 
        remote = "C:/latest.png"
 
        self.write(f'SAVE:IMAGE "{remote}"')
 
        self.wait_opc()
 
        data = self.read_file(remote)
 
        if filename is None:
            filename = self.save_dir / f"MSO24_{self._timestamp()}.png"
 
        filename = Path(filename)
 
        with open(filename, "wb") as f:
            f.write(data)
 
        return filename
 
    # =====================================================
    # Waveforms
    # =====================================================
 
    def save_channel_csv(self, channel, filename=None):
 
        remote = f"C:/{channel}.csv"
 
        self.write(f'SAVE:WAVEFORM {channel},"{remote}"')
 
        self.wait_opc()
 
        data = self.read_file(remote)
 
        if filename is None:
            filename = self.save_dir / f"{self._timestamp()}_{channel}.csv"
 
        filename = Path(filename)
 
        with open(filename, "wb") as f:
            f.write(data)
 
        return filename
 
    def save_all_channels(self, channels=("CH1", "CH2", "CH3", "CH4")):
 
        files = []
 
        for ch in channels:
            try:
                files.append(self.save_channel_csv(ch))
 
            except Exception as e:
                print(f"{ch} failed:", e)
 
        return files
 
    # =====================================================
    # Setup
    # =====================================================
 
    def save_setup(self, filename=None):
 
        remote = "C:/scope_setup.set"
 
        self.write(f'SAVE:SETUP "{remote}"')
 
        self.wait_opc()
 
        data = self.read_file(remote)
 
        if filename is None:
            filename = self.save_dir / f"{self._timestamp()}_setup.set"
 
        filename = Path(filename)
 
        with open(filename, "wb") as f:
            f.write(data)
 
        return filename
 
    def screenshot_bytes(self):
 
        remote = "C:/latest.png"
 
        self.write(f'SAVE:IMAGE "{remote}"')
 
        self.wait_opc()
 
        return self.read_file(remote)