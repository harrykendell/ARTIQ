"""Thin ctypes binding for Pico's official Linux libusbtc08 SDK."""
from __future__ import annotations

import ctypes as ct
import math
import os
from ctypes.util import find_library
from pathlib import Path

from .store import THERMOCOUPLE_TYPES


class PicoError(OSError):
    pass


class PicoTC08:
    """One unit/handle; only the acquisition loop may instantiate this class."""
    def __init__(self, library=None):
        # The Pico Debian SDK is also supported as a user-owned extraction,
        # avoiding a system-wide installation on the laboratory PC.
        user_sdk = (Path.home() / ".local/share/tc08-sdk/opt/picoscope/lib/"
                    "libusbtc08.so")
        library_path = (os.getenv("PICO_TC08_LIBRARY") or find_library("usbtc08")
                        or (str(user_sdk) if user_sdk.is_file()
                            else "libusbtc08.so"))
        self.lib = library or ct.CDLL(library_path)
        self.lib.usb_tc08_open_unit.restype = ct.c_int16
        self.lib.usb_tc08_close_unit.argtypes = [ct.c_int16]
        self.lib.usb_tc08_close_unit.restype = ct.c_int16
        self.lib.usb_tc08_set_mains.argtypes = [ct.c_int16, ct.c_int16]
        self.lib.usb_tc08_set_mains.restype = ct.c_int16
        self.lib.usb_tc08_set_channel.argtypes = [ct.c_int16, ct.c_int16, ct.c_int8]
        self.lib.usb_tc08_set_channel.restype = ct.c_int16
        self.lib.usb_tc08_get_single.argtypes = [
            ct.c_int16, ct.POINTER(ct.c_float), ct.POINTER(ct.c_int16), ct.c_int16
        ]
        self.lib.usb_tc08_get_single.restype = ct.c_int16
        self.lib.usb_tc08_get_last_error.argtypes = [ct.c_int16]
        self.lib.usb_tc08_get_last_error.restype = ct.c_int16
        self.handle = None

    def _check(self, result, operation):
        if result != 1:
            error = self.lib.usb_tc08_get_last_error(self.handle or 0)
            raise PicoError(f"{operation} failed (SDK error {error})")

    def open(self):
        if self.handle is not None:
            raise PicoError("Pico logger already open")
        handle = self.lib.usb_tc08_open_unit()
        if handle <= 0:
            raise PicoError(f"Pico TC-08 unavailable (handle={handle})")
        self.handle = handle
        try:
            self._check(self.lib.usb_tc08_set_mains(handle, 0), "set_mains(50Hz)")
            self._check(self.lib.usb_tc08_set_channel(handle, 0, ord("C")),
                        "enable cold junction")
        except Exception:
            self.close()
            raise

    def configure(self, channels):
        if self.handle is None:
            raise PicoError("TC-08 is closed")
        for entry in channels:
            ch = entry["channel"]
            kind = entry["type"] if entry["enabled"] else " "
            if kind not in THERMOCOUPLE_TYPES and kind != " ":
                raise ValueError("Unsupported TC-08 thermocouple type")
            self._check(self.lib.usb_tc08_set_channel(self.handle, ch, ord(kind)),
                        f"set_channel({ch})")

    def read(self, enabled_channels):
        if self.handle is None:
            raise PicoError("TC-08 is closed")
        values = (ct.c_float * 9)()
        overflow = ct.c_int16()
        self._check(self.lib.usb_tc08_get_single(self.handle, values, ct.byref(overflow), 0),
                    "get_single")
        cjc = float(values[0])
        if not math.isfinite(cjc) or overflow.value & 1:
            cjc = None
        readings = {}
        for ch in enabled_channels:
            value = float(values[ch])
            ok = math.isfinite(value) and not (overflow.value & (1 << ch))
            readings[ch] = {
                "value_c": value if ok else None,
                "status": "ok" if ok else ("overflow" if overflow.value & (1 << ch) else "invalid"),
            }
        return readings, cjc

    def close(self):
        handle = self.handle
        self.handle = None
        if handle is not None:
            self.lib.usb_tc08_close_unit(handle)
