#!/usr/bin/env python3
"""Watch the next ARTIQ run and capture RTIO analyser artifacts.

Run this on the ARTIQ server, preferably from the ARTIQ repository and inside the
same nix shell/environment used for normal ARTIQ commands.

Example on the server:

    nix shell
    python3 tools/rtio/rtio_watch_next_capture.py \
        --device-db repository/models/device_db.py \
        --master 137.222.69.28 \
        --out-dir /tmp/rtio_captures

Then start one experiment from your local machine or dashboard. The script waits
for that RID to finish, dumps the RTIO analyser buffer, decodes it, writes a VCD
when possible, and stores the core log.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import time


def run(
    cmd: list[str],
    *,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    print("+ " + " ".join(cmd), flush=True)
    stdout = stdout_path.open("wb") if stdout_path else None
    stderr = stderr_path.open("wb") if stderr_path else None
    try:
        return subprocess.run(cmd, stdout=stdout, stderr=stderr, check=check)
    finally:
        if stdout:
            stdout.close()
        if stderr:
            stderr.close()


def drain_analyzer(device_db: str, output_dir: Path) -> None:
    """Empty stale analyser data before the watched run starts."""
    run(
        [
            "artiq_coreanalyzer",
            "--device-db",
            device_db,
            "-d",
            str(output_dir / "pre_run_drain.dump"),
        ],
        stderr_path=output_dir / "pre_run_drain.stderr",
        check=False,
    )


def wait_for_next_rid(timeout: float, poll: float, log_path: Path) -> int:
    from sipyco.pc_rpc import Client

    deadline = time.time() + timeout if timeout > 0 else None
    with log_path.open("w", encoding="utf-8") as log:
        remote = Client("127.0.0.1", 3251, "schedule")
        try:
            baseline_status = remote.get_status()
            baseline = set(baseline_status.keys())
            print(
                "BASELINE_RIDS:",
                " ".join(str(rid) for rid in sorted(baseline)),
                file=log,
                flush=True,
            )

            rid = None
            while rid is None:
                status = remote.get_status()
                new_rids = sorted(r for r in status.keys() if r not in baseline)
                if new_rids:
                    rid = int(new_rids[0])
                    print("RID:", rid, file=log, flush=True)
                    break
                if deadline is not None and time.time() > deadline:
                    raise TimeoutError("no new RID appeared")
                time.sleep(poll)

            last_status = None
            while True:
                status = remote.get_status()
                run_status = status.get(rid)
                if run_status is None:
                    print("RID_DONE:", rid, file=log, flush=True)
                    return rid
                current_status = run_status.get("status")
                if current_status != last_status:
                    print("STATUS:", current_status, file=log, flush=True)
                    last_status = current_status
                if deadline is not None and time.time() > deadline:
                    raise TimeoutError(f"RID {rid} did not finish")
                time.sleep(poll)
        finally:
            remote.close_rpc()


def capture_artifacts(device_db: str, output_dir: Path) -> None:
    dump_path = output_dir / "rtio.dump"
    decoded_path = output_dir / "rtio.decoded"
    vcd_path = output_dir / "rtio.vcd"

    run(["artiq_coreanalyzer", "--device-db", device_db, "-d", str(dump_path)])
    run(
        ["artiq_coreanalyzer", "--device-db", device_db, "-r", str(dump_path), "-p"],
        stdout_path=decoded_path,
    )
    run(
        [
            "artiq_coreanalyzer",
            "--device-db",
            device_db,
            "-r",
            str(dump_path),
            "-w",
            str(vcd_path),
        ],
        stderr_path=output_dir / "vcd.stderr",
        check=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-db", default="repository/models/device_db.py")
    parser.add_argument(
        "--out-dir",
        default="/tmp/rtio_captures",
        help="remote capture parent directory",
    )
    parser.add_argument("--prefix", default="rtio", help="capture directory prefix")
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="seconds to wait for run start and finish; <=0 disables timeout",
    )
    parser.add_argument(
        "--poll", type=float, default=0.5, help="scheduler polling interval in seconds"
    )
    parser.add_argument(
        "--no-drain",
        action="store_true",
        help="do not drain old analyser data before watching",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.out_dir).expanduser().resolve() / f"{args.prefix}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)

    print(f"Capture directory: {output_dir}")
    if not args.no_drain:
        drain_analyzer(args.device_db, output_dir)

    print("Waiting for the next RID. Start exactly one experiment now.")
    rid = wait_for_next_rid(args.timeout, args.poll, output_dir / "watch.log")
    print(f"RID {rid} finished; capturing analyser buffer.")
    capture_artifacts(args.device_db, output_dir)

    print(f"Done: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
