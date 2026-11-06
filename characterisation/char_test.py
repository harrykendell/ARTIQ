#!/usr/bin/env python3
"""
Smoke test for the characterisation scripts: submit ONE tiny example of every
step type, run them one at a time, and report PASS/FAIL for each from the
datasets ndscan writes (ndscan.rid_<RID>.completed / points / optimizer.*).

It imports a characterisation script (cmot_char.py by default) and reuses its
parameter names, sequence overrides, benchmark experiment and validation, so it
tests exactly the code the full run will use -- only the sizes are shrunk:

    benchmark thermometry   2 expansion times x 1 repeat           2 shots
    benchmark shot          1 shot                                  1 shot
    1D scan                 3 points x 1 repeat                     3 shots
    parameter thermometry   2 values x 2 expansion times            4 shots
    LHS (optimise mode)     max_evals = 6, 1 repeat, ref every 2    6 shots
                                                                   ---------
                                                                   16 shots

Usage (run from the folder holding the characterisation scripts)
-----
    python char_smoke_test.py --offline                  # print the plan only
    python char_smoke_test.py --dry-run                  # validate against the master, submit nothing
    python char_smoke_test.py                            # run the test with cmot_char.py
    python char_smoke_test.py --script pgc_pgc_char      # test a companion script instead
    python char_smoke_test.py --param CMOT_Z_current     # scan a different parameter
    python char_smoke_test.py --keep-going               # don't stop at the first failure
"""
from __future__ import annotations

import argparse
import importlib
import logging
import sys
import time
from datetime import datetime

SCRIPTS = ("cmot_char", "cmot_pgc_char", "pgc_pgc_char")


def shrink(c, param):
    """Cut every size in the imported characterisation module down to a few shots."""
    def two_from(tofs):                       # a mid and a late expansion time
        return [tofs[len(tofs) // 2], tofs[-1]]

    c.TOF_BENCH_THERM_MS = two_from(c.TOF_BENCH_THERM_MS)
    c.TOF_PARAM_THERM_MS = two_from(c.TOF_PARAM_THERM_MS)
    c.BENCH_THERM_REPEATS = 1
    c.BENCH_SHOT_REPEATS = 1
    c.SCAN_POINTS, c.SCAN_REPEATS = 3, 1
    c.PARAM_THERM_POINTS = 2

    # Parameter thermometry: 2 values at 25 % and 75 % of the range instead of the CSV,
    # so the test needs no data file and avoids the extremes of the range.
    def load_column(key, n):
        p = c.PARAMS[key]
        return [p["lo"] + f * (p["hi"] - p["lo"]) for f in (0.25, 0.75)][:n]
    c.load_column = load_column

    # Optimise mode: stays inside the LHS phase (int(10*sqrt(7)) = 26 initial points),
    # reference re-measured every 2 candidates so the subtraction path is exercised.
    c.LHS_OPTIMISE = {
        **c.LHS_OPTIMISE,
        "algorithm": {**c.LHS_OPTIMISE["algorithm"], "n_init": 10},   # minimum allowed
        "num_repeats_per_point": 1,
        "max_evals": 6,
        "reference_resample_interval": 2,
    }

    if param not in c.PARAMS:
        raise SystemExit(f"--param {param!r} is not one of {list(c.PARAMS)}")
    return [
        c.benchmark_thermometry(),
        c.benchmark_shot(),
        c.scan_1d(param),
        c.param_thermometry(param),
        c.lhs(),
    ]


# Running and checking

def get_dataset(datasets, key):
    try:
        return datasets.get(key)
    except Exception:          # KeyError comes back over RPC as a remote exception
        return None


def wait_for(scheduler, rid, timeout_s):
    """Wait until the RID leaves the schedule. Returns False on timeout."""
    t0, last = time.monotonic(), None
    while True:
        status = scheduler.get_status().get(rid)
        if status is None:
            return True
        state = status.get("status")
        if state != last:
            print(f"        {state}")
            last = state
        if time.monotonic() - t0 > timeout_s:
            return False
        time.sleep(1.0)


def check(datasets, rid, step):
    """PASS/FAIL from the datasets ndscan broadcasts for this RID."""
    prefix = f"ndscan.rid_{rid}."
    completed = get_dataset(datasets, prefix + "completed")
    if completed is None:
        return False, "never started: build/prepare failed (see the master log for this RID)"
    if not completed:
        return False, "started but did not complete: exception or termination (see the master log)"

    n_points = len(get_dataset(datasets, prefix + "points.axis_0") or [])
    mode = get_dataset(datasets, prefix + "execution_mode")
    if step.optimise is not None:
        reason = get_dataset(datasets, prefix + "optimizer.termination_reason")
        best = get_dataset(datasets, prefix + "optimizer.best_value")
        ok = mode == "optimise" and n_points > 0
        return ok, (f"mode={mode}, {n_points} points, termination={reason!r}, "
                    f"best objective={best}")
    ok = mode == "scan" and n_points == step.shots
    return ok, f"mode={mode}, {n_points}/{step.shots} points"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", default="cmot_char", choices=SCRIPTS,
                    help="characterisation script to test (default: cmot_char)")
    ap.add_argument("--param", help="parameter for the 1D scan / thermometry "
                                    "(default: the first parameter of the script)")
    ap.add_argument("--offline", action="store_true", help="print the plan, no master needed")
    ap.add_argument("--dry-run", action="store_true", help="validate against the master, submit nothing")
    ap.add_argument("--keep-going", action="store_true", help="run every step even after a failure")
    ap.add_argument("--timeout", type=float, default=900, help="seconds allowed per step (default 900)")
    opts = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    c = importlib.import_module(opts.script)
    trees = None if opts.offline else c.prepare_units()   # experiment's unit scales first
    steps = shrink(c, opts.param or next(iter(c.PARAMS)))
    for s in steps:
        s.label = f"[smoke] {s.label}"

    print(f"Smoke test of {opts.script}.py\n")
    c.print_plan(steps, 0)
    shots = sum(s.shots for s in steps)
    print(f"(about {shots * c.SHOT_PERIOD_S / 60:.0f} min of shots, plus ~10 s per step to start up)")
    if opts.offline:
        return 0

    expids = c.build_expids(steps, 0, trees)   # validates every step first
    if opts.dry_run:
        print(f"\nDry run OK: {len(expids)} steps validated against the parameter tree.")
        return 0

    from sipyco.pc_rpc import Client
    scheduler = Client(c.MASTER, c.PORT, "schedule")
    datasets = Client(c.MASTER, c.PORT, "dataset_db")
    results = []
    try:
        for i, step, expid in expids:
            rid = scheduler.submit(c.PIPELINE, expid, 0, None, False)
            print(f"\n[{i}] RID {rid}  {step.kind}  {step.label}")
            if not wait_for(scheduler, rid, opts.timeout):
                scheduler.request_termination(rid)
                ok, msg = False, f"timed out after {opts.timeout:g} s; termination requested"
            else:
                ok, msg = check(datasets, rid, step)
            results.append((i, rid, step, ok, msg))
            print(f"    {'PASS' if ok else 'FAIL'}: {msg}")
            if not ok and not opts.keep_going:
                print("\nStopping at the first failure (use --keep-going to run the rest).")
                break
    except KeyboardInterrupt:
        print("\nInterrupted. A queued or running RID stays in the schedule until deleted.")
    finally:
        scheduler.close_rpc()
        datasets.close_rpc()

    print(f"\n{'=' * 72}\nSmoke test of {opts.script}.py  ({datetime.now():%Y-%m-%d %H:%M})")
    for i, rid, step, ok, msg in results:
        print(f"  {'PASS' if ok else 'FAIL'}  RID {rid:<7} {step.kind:<22} {msg}")
    n_pass = sum(r[3] for r in results)
    print(f"{n_pass}/{len(steps)} steps passed")
    return 0 if n_pass == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
