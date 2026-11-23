#!/usr/bin/env python3
"""Submit one AbsorptionImage run, retaining its full ndscan parameter tree."""

import logging
import sys

from sipyco import pyon
from sipyco.pc_rpc import Client

FILE = "repository/imaging/absorption_image.py"
CLASS = "AbsorptionImage"
PARAMETER = "repository.fragments.mot.MOT.loading_time"
PATH = "MOT"
VALUE = 5.0  # seconds; change this and PARAMETER/PATH for another override


def main():
    db = Client("::1", 3251, "experiment_db")
    try:
        arginfo = db.examine(FILE)[CLASS]["arginfo"]
    finally:
        db.close_rpc()

    if set(arginfo) != {"ndscan_params"}:
        raise RuntimeError(f"Unexpected experiment arguments: {list(arginfo)}")
    params = pyon.decode(arginfo["ndscan_params"][0]["default"])
    if not params.get("schemata") or not params.get("instances"):
        raise RuntimeError("Missing ndscan parameter metadata")
    if PARAMETER not in params["instances"].get(PATH, []):
        raise ValueError(f"Unknown parameter/path: {PARAMETER} / {PATH}")
    params["overrides"][PARAMETER] = [{"path": PATH, "value": VALUE}]

    expid = {
        "file": FILE,
        "class_name": CLASS,
        "arguments": {"ndscan_params": pyon.encode(params)},
        "argument_defaults": {},
        "repo_rev": None,
        "devarg_override": {},
        "log_level": logging.WARNING,
    }

    if sys.argv[1:] == ["--dry-run"]:
        print(f"Dry run: {len(params['schemata'])} parameter schemata, "
              f"{len(params['instances'])} fragment instances; "
              f"{PARAMETER} ({PATH}) = {VALUE!r}")
        return
    if sys.argv[1:]:
        raise SystemExit("Usage: submit_absorption_image.py [--dry-run]")

    scheduler = Client("::1", 3251, "schedule")
    try:
        rid = scheduler.submit("main", expid, 0, None, False)
    finally:
        scheduler.close_rpc()
    print(f"Submitted AbsorptionImage as RID {rid}")


if __name__ == "__main__":
    main()
