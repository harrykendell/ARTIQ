#!/usr/bin/env python3
"""Prepare, rebuild or reflash the lab's explicitly qualified firmware pair."""

import argparse
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "crate config"
PIN = CONFIG / "firmware.json"
IMAGES = ("top.bit", "runtime.fbi")


def sha256(path):
    # The lab's system Python is 3.10; no dependency on hashlib.file_digest.
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path, expected):
    if not path.is_file() or sha256(path) != expected:
        raise RuntimeError(f"Missing or checksum-mismatched file: {path}")


def load_pin():
    pin = json.loads(PIN.read_text())
    for name in ("source_revision", "toolchain_revision"):
        if not re.fullmatch(r"[0-9a-f]{40}", pin[name]):
            raise ValueError(f"{name} must be a full Git commit")
    for name in ("source_repo", "toolchain_repo"):
        if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+", pin[name]):
            raise ValueError(f"invalid repository URL: {name}")
    if not re.fullmatch(r"bu2402001-[\w.-]+", pin["release"]):
        raise ValueError("invalid release tag")
    if pin["board"] != "bu2402001.json" or set(pin["files"]) != set(IMAGES):
        raise ValueError("unexpected board or firmware files")
    if "--analyzer-telemetry" not in pin["build_flags"]:
        raise ValueError("the lab requires extended analyser telemetry")
    board_path = CONFIG / pin["board"]
    verify_file(board_path, pin["board_sha256"])
    board = json.loads(board_path.read_text())
    if (
        board["target"] != "kasli"
        or board["variant"].lower() != "bu2402001"
        or board["base"] != "standalone"
        or board["hw_rev"] != "v2.0"
    ):
        raise ValueError("firmware pin does not match the laboratory crate")
    return pin, board


def fetch_file(url, dest, expected):
    if dest.exists():
        verify_file(dest, expected)
        return
    # Never leave an incomplete download at the qualified image path.
    fd, temporary = tempfile.mkstemp(prefix=dest.name + ".", dir=dest.parent)
    path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as out:
            with urlopen(
                Request(url, headers={"User-Agent": "lab-artiq-firmware"}), timeout=60
            ) as response:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
        verify_file(path, expected)
        path.replace(dest)
    finally:
        path.unlink(missing_ok=True)


def qualified_dir(pin):
    return CONFIG / "bu2402001_qualified" / pin["release"]


def prepare(pin):
    directory = qualified_dir(pin)
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{pin['source_repo']}/releases/download/{pin['release']}"
    for name, digest in pin["files"].items():
        fetch_file(f"{base}/{name}", directory / name, digest)
        print(f"Verified {name}: {digest}", flush=True)
    return directory


def board_command(pin, command, *, source=False):
    prefix = "source" if source else "toolchain"
    flake = f"git+{pin[prefix + '_repo']}?rev={pin[prefix + '_revision']}#boards"
    return [
        "nix",
        "--extra-experimental-features",
        "nix-command flakes",
        "develop",
        "--accept-flake-config",
        "--no-write-lock-file",
        flake,
        "--command",
        *command,
    ]


def flash_command(directory, *, dry_run=False):
    # Do not overwrite bootloader, configuration storage or unrelated flash.
    return [
        "artiq_flash",
        *(["-n"] if dry_run else []),
        "-t",
        "kasli",
        "-d",
        str(directory),
        "gateware",
        "firmware",
        "start",
    ]


def require_idle_host(host):
    """Require a deliberate maintenance window, not merely an empty queue."""
    viewer = subprocess.run(
        ["systemctl", "show", "artiq-viewer.service", "-p", "ActiveState", "--value"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if viewer != "inactive":
        raise RuntimeError(
            "Stop artiq-viewer.service before flashing (sudo systemctl stop artiq-viewer.service)"
        )
    listening = subprocess.check_output(["ss", "-ltnH"], text=True)
    for line in listening.splitlines():
        if re.search(r":(?:3250|3251|1385|1386)\s", line):
            raise RuntimeError(
                "Stop the master/controller stack and dashboard before flashing"
            )
    names = {
        "artiq_master",
        "artiq_run",
        "artiq_worker",
        "artiq_dashboard",
        "aqctl_coreanalyzer_proxy",
    }
    modules = {
        "artiq.master.worker_impl",
        "artiq.frontend.artiq_run",
        "artiq.frontend.artiq_master",
    }
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(
            Path(a).name.removeprefix(".").removesuffix("-wrapped") in names
            for a in args
        ):
            raise RuntimeError(f"ARTIQ process still running: PID {proc.name}")
        if any(a in modules for a in args):
            raise RuntimeError(f"ARTIQ process still running: PID {proc.name}")
    connections = subprocess.check_output(["ss", "-tnH"], text=True)
    if re.search(rf"\b{re.escape(host)}:(?:1381|1382|1392|1393)\s", connections):
        raise RuntimeError("Disconnect all kernel and analyser clients before flashing")


def read_exact(sock, count):
    data = bytearray()
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise RuntimeError("truncated snapshot response")
        data.extend(part)
    return bytes(data)


def verify_snapshot(pin, host):
    expected = pin["snapshot"]
    tail = 2**64 - 1
    token = uuid.uuid4().bytes
    with socket.create_connection((host, expected["port"]), timeout=5) as sock:
        sock.sendall(struct.pack("<4sQ16s", b"RTQ9", tail, token))
        magic, flags, requested, start, end, observed, capacity, channel = (
            struct.unpack("<4sIQQQQII", read_exact(sock, 48))
        )
        if not (
            magic == b"RTS1"
            and flags == 0
            and requested == tail
            and start == end == observed
            and capacity == expected["capacity"]
            and channel == expected["log_channel"]
        ):
            raise RuntimeError("unexpected analyser header")
        signature, *values = struct.unpack("<4s11Q16s8Q", read_exact(sock, 172))
        if (
            signature != b"RTP4"
            or values[11] != token
            or values[12] != expected["features"]
        ):
            raise RuntimeError("extended analyser telemetry not enabled")
    for port in (1382, 1393):
        try:
            connection = socket.create_connection((host, port), timeout=1)
        except ConnectionRefusedError:
            continue
        except TimeoutError:
            # No service accepted a connection; the verified production
            # endpoint above remains the authoritative capability check.
            continue
        else:
            connection.close()
            raise RuntimeError(f"unexpected analyser endpoint on port {port}")
    print("Verified 2 MiB RTQ9/RTP4 analyser with hardware telemetry", flush=True)


def wait_core(pin, host):
    from artiq.coredevice.comm_kernel import CommKernel, Reply, Request as KernelRequest

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        c = CommKernel(host)
        try:
            c.open()
            c.socket.settimeout(4)
            c._write_empty(KernelRequest.SystemInfo)
            c._flush()
            c._read_header()
            c._read_expect(Reply.SystemInfo)
            device_type, identity, clean = c._read(4), c._read_string(), c._read_bool()
            if device_type != b"AROR" or identity != pin["identity"] or not clean:
                raise RuntimeError(
                    f"Unexpected core identity/state: {device_type}, {identity}, {clean}"
                )
            print(f"Core ready: {identity}", flush=True)
            return
        except OSError:
            time.sleep(1)
        finally:
            c.close()
    raise RuntimeError("Core did not become ready; keep master stopped")


def configure(pin, host):
    from artiq.coredevice.comm_mgmt import CommMgmt

    # Bound management connection and readiness waits after reboot.
    socket.setdefaulttimeout(4)
    wait_core(pin, host)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        c = CommMgmt(host)
        try:
            c.open()
            c.socket.settimeout(4)
            c.get_log()
            break
        except OSError:
            time.sleep(1)
        finally:
            c.close()
    else:
        raise RuntimeError("Core management not ready")
    c = CommMgmt(host)
    changed = False
    try:
        c.open()
        c.socket.settimeout(4)
        for key, value in pin["config"].items():
            try:
                current = c.config_read(key)
            except OSError as error:
                if "key may not exist" not in str(error):
                    raise
                current = None
            if current != value:
                c.config_write(key, value.encode())
                changed = True
            if c.config_read(key) != value:
                raise RuntimeError(f"configuration verification failed: {key}")
            print(f"Verified {key}={value}", flush=True)
        if changed:
            c.reboot()
    finally:
        c.close()
    if changed:
        time.sleep(2)
        wait_core(pin, host)
    verify_snapshot(pin, host)


def flash_inside_board_shell(pin, board):
    directory = qualified_dir(pin)
    for name, expected in pin["files"].items():
        verify_file(directory / name, expected)
    require_idle_host(board["core_addr"])
    # Always verify the pinned pair immediately before writing.
    subprocess.run(flash_command(directory), check=True)
    configure(pin, board["core_addr"])
    print(
        "Flash and protocol verification complete. Restart viewer and ARTIQ stack.",
        flush=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "dry-run", "build", "flash"),
        nargs="?",
        default="prepare",
    )
    parser.add_argument(
        "--confirm-idle",
        action="store_true",
        help="confirm apparatus safe, all kernels stopped and maintenance window active",
    )
    parser.add_argument("--board-shell", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    pin, board = load_pin()
    print(f"Qualified {pin['release']} from {pin['source_revision']}", flush=True)
    if args.action == "build":
        # Build from the exact fork source and its locked toolchain. A full
        # rebuild is NOT necessarily byte-identical to the qualified images.
        destination = CONFIG / f"bu2402001_build_{pin['source_revision'][:12]}"
        if destination.exists():
            raise RuntimeError(
                f"Build directory exists; move it aside first: {destination}"
            )
        subprocess.run(
            board_command(
                pin,
                [
                    "python",
                    "-m",
                    "artiq.gateware.targets.kasli",
                    *pin["build_flags"],
                    "--output-dir",
                    str(destination),
                    str(CONFIG / pin["board"]),
                ],
                source=True,
            ),
            check=True,
            cwd=ROOT,
        )
        print(
            f"Unqualified build at {destination}; validate timing and hardware before publishing a new release. Nothing flashed."
        )
        return
    if args.action == "flash":
        if not args.confirm_idle:
            parser.error(
                "flash requires --confirm-idle; stop the viewer/master/dashboard and ensure the apparatus is safe"
            )
        require_idle_host(board["core_addr"])
        if args.board_shell:
            flash_inside_board_shell(pin, board)
            return
    directory = prepare(pin)
    if args.action == "dry-run":
        subprocess.run(
            board_command(pin, flash_command(directory, dry_run=True)), check=True
        )
    elif args.action == "flash":
        subprocess.run(
            board_command(
                pin,
                [
                    "python",
                    str(Path(__file__).resolve()),
                    "flash",
                    "--confirm-idle",
                    "--board-shell",
                ],
            ),
            check=True,
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Firmware operation failed: {exc}", file=sys.stderr)
        sys.exit(1)
