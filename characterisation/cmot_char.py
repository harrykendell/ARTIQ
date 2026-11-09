#!/usr/bin/env python3
"""
Submit the CMOT characterisation run (benchmarks, 1D scans, parameter
thermometry, LHS optimisation) to the ARTIQ master as ndscan experiments.

Every step starts from the experiment's full ndscan parameter tree (read from
experiment_db), adds overrides / scan axes, and is validated against the tree
BEFORE anything is submitted : a typo in an FQN or path aborts the whole
run instead of failing halfway through the night.

Usage
-----
    python cmot_char.py --list-params cmot      # list parameters whose name contains "cmot"
    python cmot_char.py --offline               # print plan, no master needed
    python cmot_char.py --dry-run               # build + validate against master, submit nothing
    python cmot_char.py                         # queue everything
    python cmot_char.py --wait                  # submit one at a time, wait for each
    python cmot_char.py --wait --start-at 12    # resume from step 12

Lines marked  # EDIT  must match your repository (FQNs/paths: --list-params or the GUI).
ndscan stores values in SI base units (s, A, Hz ...); `scale` below converts lab units.
"""
from __future__ import annotations

import argparse
import copy
import csv
import logging
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MASTER, PORT = "::1", 3251
PIPELINE = "main"

ABS_IMAGE = ("repository/imaging/absorption_image.py", "AbsorptionImage")
BENCH = ("repository/benchmark/benchmark.py", "CMOTCharBench")   # CMOTBench with LOADING_TIME = 5 s
EXPERIMENTS = {
    "benchmark_thermometry": BENCH,
    "benchmark_shot":        ABS_IMAGE,
    "scan_1d":               ABS_IMAGE,
    "param_thermometry":     ABS_IMAGE,
    "lhs":                   ABS_IMAGE,   # ndscan execution_mode = "optimise"
}


# Parameters: (fqn, path) in the ndscan tree, run-sheet default/range in lab units

# FQN = "<fragment class FQN>.<parameter name>"; names as shown in the GUI.
PARAM_FQN_PREFIX, PARAM_PATH = "repository.fragments.mot.MOT", "MOT"

# Run-sheet values in lab units; `scale` converts to the SI value ndscan stores.
# lo/hi = 1D-scan min/max (21 points x 5 repeats) and the LHS search box.
# csv_col = column in PARAM_THERM_FILE holding that parameter's 30 sample points.
# Values below are in the GUI's display units (Γ, ms, mA, dB ...). The conversion to
# the SI value ndscan stores is read from each experiment's own parameter schema
# before anything is built (see load_unit_scales), exactly as the GUI does it.
# `scale` here is only a fallback for --offline and a cross-check.
GAMMA_HZ = 6.0666e6       # Γ/2π of the Rb-87 D2 line, Hz (fallback only)

PARAMS = {
    "CMOT_detuning":           dict(default=9.65,  lo=6.0,  hi=12.0,  scale=GAMMA_HZ, unit="Γ"),
    "CMOT_duration":           dict(default=4.0,   lo=0.5,  hi=10.0,  scale=1e-3, unit="ms"),
    "CMOT_settle_time":        dict(default=3.79,  lo=1.5,  hi=10.0,  scale=1e-3, unit="ms"),
    "CMOT_repump_detuning":    dict(default=0.075, lo=0.0,  hi=5.0,   scale=GAMMA_HZ, unit="Γ"),
    "CMOT_repump_attenuation": dict(default=3.09,  lo=0.0,  hi=5.0,   scale=1.0,  unit="dB"),
    "CMOT_Y_current":          dict(default=0.84,  lo=0.3,  hi=5.0,   scale=1e-3, unit="mA"),  # lo = smallest supply setting
    "CMOT_Z_current":          dict(default=59.8,  lo=10.0, hi=100.0, scale=1e-3, unit="mA"),
    # CMOT_X_current is not on the run sheet: left at the experiment default.
}
for _name, _p in PARAMS.items():
    _p.setdefault("fqn", f"{PARAM_FQN_PREFIX}.{_name}")
    _p.setdefault("path", PARAM_PATH)
    _p.setdefault("csv_col", _name)                                  

# Expansion time lives in a different fragment in each experiment: (fqn, path).
# Path "" = the experiment's top-level ExpFragment.
TOF_PARAM = {
    ABS_IMAGE: ("absorption_image.AbsorptionImageExpFrag.expansion_time", ""),
    BENCH:     ("benchmark.CMOTCharBenchFragment.expansion_time", ""),
}
TOF_SCALE = 1e-3          # ms -> s

# MOT loading time shared by ALL steps. The benchmark fixes its own value at build
# time (not settable from here) -- keep CMOTCharBenchFragment.LOADING_TIME equal.
LOADING_TIME_S = 5.0

# Sequence configuration. CMOTBench fixes these inside CMOTBenchFragment
# (_TOFBenchmarkExpFrag.build_fragment), so they are NOT free parameters there and
# must not be overridden. AbsorptionImage leaves them free, so the same values are
# pinned on every AbsorptionImage step -- scans and benchmarks then run an identical
# sequence (image straight after the CMOT stage, same MOT loading time).
_AI = "absorption_image.AbsorptionImageExpFrag"
STAGE_OVERRIDES = {
    ABS_IMAGE: [
        (f"{_AI}.do_cmot",          "", True),
        (f"{_AI}.do_pgc",           "", False),
        (f"{_AI}.trap_frequency",   "", False),
        (f"{_AI}.ODT_active",       "", False),
        (f"{_AI}.do_evaporation1",  "", False),
        (f"{_AI}.do_evaporation2",  "", False),
        ("repository.fragments.mot.MOT.loading_time", "MOT", LOADING_TIME_S),
    ],
    BENCH: [],
}

HOLD = {}

# Run-sheet constants pinned on every step, in GUI units (converted and unit-checked
# like PARAMS):  fqn: (path, value, unit)
CONSTANTS = {
    "repository.fragments.mot.MOT.MOT_loading_gradient": ("MOT", 0.8, "A"),
}

# Further constants pinned on every step (fqn, path, SI value). Empty -> experiment defaults.
FIXED = []

# True: write the run-sheet defaults as explicit overrides on every step, so the
# run does not change if someone edits the defaults in the GUI mid-run.
PIN_DEFAULTS = True

# Parameters an experiment fixes in its own code, so they are not free there and
# cannot be overridden. They are skipped on that experiment's steps only; the
# experiment then uses its own value -- keep that equal to the run-sheet default.
NOT_SETTABLE = {}

# Measurement settings (run sheet)

TOF_PARAM_THERM_MS = [6.0, 8.0, 12.0, 15.0, 18.0, 22.0]   # parameter-thermometry expansion times
TOF_BENCH_THERM_MS = [6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]  # = CMOT_TOF_TIMES in benchmark.py
TOF_SINGLE_MS = 12.0

SCAN_POINTS, SCAN_REPEATS = 21, 5
BENCH_THERM_REPEATS, BENCH_SHOT_REPEATS = 3, 3
PARAM_THERM_POINTS = 30
PARAM_THERM_FILE = Path("LHS_initial_samples_temp_cmot.csv")  # 30 rows, one column per parameter
RANDOMISE = False                       # shuffle points within an axis

# ndscan scan options applied to every step (step builders override num_repeats).
# num_repeats repeats the whole scan; num_repeats_per_point repeats each point
# back to back. All repeats in this script use num_repeats.
SCAN_DEFAULTS = {
    "num_repeats": 1,
    "num_repeats_per_point": 1,
    "randomise_order_globally": False,
    "no_axes_mode": "single",
    "skip_on_persistent_transitory_error": False,
}

# LHS = ndscan optimisation (ndscan/experiment/optimize.py). Sent as
#   params["execution_mode"] = "optimise"          (ExecutionMode.optimise.name; default "scan")
#   params["optimise"]       = {...}                (below; merged over the experiment's defaults)
# Each optimised parameter gets {fqn, path, min, max, initial}; "initial" is the run-sheet
# default and is also the reference point that is re-measured and subtracted.
LHS_OPTIMISE = {
    "objective": {"channel": "custom_objective", "direction": "min"},
    "algorithm": {
        "kind": "bayesian",          # "Bayesian optimization" in the GUI
        "n_init": 100,               # 264 LHS points (int(n_init*sqrt(7))) > budget: intentionally
                                     # LHS-only, the run ends before any Bayesian step
        "user_seed": -1,             # allowed -1 .. 42
        "xatol": 1e-3,
        "fatol": 1e-3,
    },
    "num_repeats_per_point": 3,
    "averaging_method": "mean",
    "max_evals": 794,                # SHOTS incl. references (~240 candidates at 3 repeats)
    "reference_normalisation": "subtract",
    "reference_resample_interval": 10,   # re-measure the default every 10 candidates
    "skip_on_persistent_transitory_error": False,
}

SHOT_PERIOD_S = 6.0                     # EDIT: only used for the time estimate

# Step description

@dataclass
class Step:
    kind: str
    label: str
    shots: int
    overrides: list = field(default_factory=list)    # [(fqn, path, SI value)]
    axes: list = field(default_factory=list)         # ndscan axis dicts
    scan: dict = field(default_factory=dict)         # merged into params["scan"]
    optimise: dict | None = None                     # set -> execution_mode "optimise"


UNIT_SCALES = {}          # fqn -> (scale, unit), read from the experiments' schemata
ALLOW_PLACEHOLDERS = False   # --offline only: preview without the thermometry CSV


def to_si(fqn, value, fallback_scale):
    """GUI display value -> SI value ndscan stores, using the experiment's own scale."""
    return float(value) * UNIT_SCALES.get(fqn, (fallback_scale,))[0]


def si(key, v):
    return to_si(PARAMS[key]["fqn"], v, PARAMS[key]["scale"])


def constant_overrides():
    return [(fqn, path, to_si(fqn, v, 1.0)) for fqn, (path, v, _unit) in CONSTANTS.items()]


def hold_overrides():
    return [(f"{PARAM_FQN_PREFIX}.{name}", PARAM_PATH, to_si(f"{PARAM_FQN_PREFIX}.{name}", v, float("nan")))
            for name, (v, _unit) in HOLD.items()]


def base_overrides(kind):
    ov = STAGE_OVERRIDES[EXPERIMENTS[kind]] + constant_overrides() + list(FIXED) + hold_overrides()
    if PIN_DEFAULTS:
        ov += [(p["fqn"], p["path"], si(k, p["default"])) for k, p in PARAMS.items()]
    skip = NOT_SETTABLE.get(EXPERIMENTS[kind], set())
    return [o for o in ov if o[0].rsplit(".", 1)[-1] not in skip]


def linear_axis(fqn, path, start, stop, n):
    return {"type": "linear", "fqn": fqn, "path": path,
            "range": {"start": start, "stop": stop, "num_points": n,
                      "randomise_order": RANDOMISE}}


def list_axis(fqn, path, values):
    return {"type": "list", "fqn": fqn, "path": path,
            "range": {"values": [float(v) for v in values], "randomise_order": RANDOMISE}}


def tof_axis(kind, tofs_ms):
    fqn, path = TOF_PARAM[EXPERIMENTS[kind]]
    return list_axis(fqn, path, [to_si(fqn, t, TOF_SCALE) for t in tofs_ms])


def tof_override(kind, tof_ms):
    """[(fqn, path, value)] fixing the expansion time, or [] if the experiment has none mapped."""
    entry = TOF_PARAM[EXPERIMENTS[kind]]
    return [(*entry, to_si(entry[0], tof_ms, TOF_SCALE))] if entry else []


def param_axis(key):
    p = PARAMS[key]
    return linear_axis(p["fqn"], p["path"], si(key, p["lo"]), si(key, p["hi"]), SCAN_POINTS)


def without(overrides, fqn, path):
    """A scanned parameter must not also carry an override."""
    return [o for o in overrides if (o[0], o[1]) != (fqn, path)]


def load_column(key, n):
    if PARAM_THERM_FILE.exists():
        import pandas as pd
        col = pd.read_csv(PARAM_THERM_FILE)[PARAMS[key]["csv_col"]].to_numpy()
        assert len(col) == n, f"{PARAM_THERM_FILE}:{key} has {len(col)} values, expected {n}"
        return col
    if not ALLOW_PLACEHOLDERS:
        raise SystemExit(f"{PARAM_THERM_FILE} not found (needed for the {key} parameter thermometry); "
                         f"nothing submitted. Put it next to this script, or use --offline to preview.")
    logging.warning("%s not found -- evenly spaced placeholder values for %s", PARAM_THERM_FILE, key)
    p = PARAMS[key]
    return [p["lo"] + i * (p["hi"] - p["lo"]) / (n - 1) for i in range(n)]


# Step builders

def benchmark_thermometry():
    return Step("benchmark_thermometry", "all defaults, TOF scan",
                len(TOF_BENCH_THERM_MS) * BENCH_THERM_REPEATS,
                overrides=base_overrides("benchmark_thermometry"), axes=[tof_axis("benchmark_thermometry", TOF_BENCH_THERM_MS)],
                scan={"num_repeats": BENCH_THERM_REPEATS})


def benchmark_shot():
    # one-point TOF axis so num_repeats applies and the TOF is recorded with the data
    return Step("benchmark_shot", f"all defaults @ {TOF_SINGLE_MS:g} ms", BENCH_SHOT_REPEATS,
                overrides=base_overrides("benchmark_shot"), axes=[tof_axis("benchmark_shot", [TOF_SINGLE_MS])],
                scan={"num_repeats": BENCH_SHOT_REPEATS})


def scan_1d(key):
    p = PARAMS[key]
    ov = without(base_overrides("scan_1d"), p["fqn"], p["path"]) + tof_override("scan_1d", TOF_SINGLE_MS)
    return Step("scan_1d", f"{key}: {p['lo']:g}-{p['hi']:g} {p['unit']}", SCAN_POINTS * SCAN_REPEATS,
                overrides=ov, axes=[param_axis(key)], scan={"num_repeats": SCAN_REPEATS})


def param_thermometry(key):
    p = PARAMS[key]
    values = [si(key, v) for v in load_column(key, PARAM_THERM_POINTS)]
    return Step("param_thermometry", f"{key} x TOF", PARAM_THERM_POINTS * len(TOF_PARAM_THERM_MS),
                overrides=without(base_overrides("param_thermometry"), p["fqn"], p["path"]),
                axes=[list_axis(p["fqn"], p["path"], values), tof_axis("param_thermometry", TOF_PARAM_THERM_MS)],
                scan={"num_repeats": 1})


def lhs():
    names = list(PARAMS)
    parameters = [dict(fqn=PARAMS[k]["fqn"], path=PARAMS[k]["path"],
                       min=si(k, PARAMS[k]["lo"]), max=si(k, PARAMS[k]["hi"]),
                       initial=si(k, PARAMS[k]["default"])) for k in names]
    ov = base_overrides("lhs")
    for k in names:                                  # optimised params carry no override
        ov = without(ov, PARAMS[k]["fqn"], PARAMS[k]["path"])
    ov += tof_override("lhs", TOF_SINGLE_MS)
    return Step("lhs", f"{len(names)}-D LHS, Bayesian (optimise)", LHS_OPTIMISE["max_evals"],
                overrides=ov, optimise={**LHS_OPTIMISE, "parameters": parameters})


def build_steps():
    return [
        benchmark_thermometry(),
        scan_1d("CMOT_settle_time"),
        benchmark_shot(),
        scan_1d("CMOT_Z_current"),
        param_thermometry("CMOT_Z_current"),
        benchmark_shot(),
        scan_1d("CMOT_detuning"),
        param_thermometry("CMOT_repump_detuning"),
        benchmark_shot(),
        lhs(),
        benchmark_thermometry(),
        param_thermometry("CMOT_duration"),
        benchmark_shot(),
        scan_1d("CMOT_duration"),
        param_thermometry("CMOT_detuning"),
        benchmark_shot(),
        scan_1d("CMOT_repump_detuning"),
        param_thermometry("CMOT_Y_current"),
        benchmark_shot(),
        scan_1d("CMOT_repump_attenuation"),
        param_thermometry("CMOT_settle_time"),
        benchmark_shot(),
        scan_1d("CMOT_Y_current"),
        param_thermometry("CMOT_repump_attenuation"),
        benchmark_thermometry(),
    ]

# ndscan parameter tree: fetch, validate, apply

def fetch_param_trees(kinds):
    """{(file, class): decoded ndscan_params default} for every experiment used."""
    from sipyco import pyon
    from sipyco.pc_rpc import Client
    trees = {}
    db = Client(MASTER, PORT, "experiment_db")
    try:
        for file, cls in {EXPERIMENTS[k] for k in kinds}:
            arginfo = db.examine(file)[cls]["arginfo"]
            if set(arginfo) != {"ndscan_params"}:
                raise RuntimeError(f"{cls}: unexpected arguments {list(arginfo)}")
            params = pyon.decode(arginfo["ndscan_params"][0]["default"])
            if not params.get("schemata") or not params.get("instances"):
                raise RuntimeError(f"{cls}: missing ndscan parameter metadata")
            trees[(file, cls)] = params
    finally:
        db.close_rpc()
    return trees


def load_unit_scales(trees):
    """Read every parameter's display unit/scale from the experiments' schemata and
    check them against the units the run-sheet values are written in."""
    UNIT_SCALES.clear()
    for params in trees.values():
        for fqn, schema in params["schemata"].items():
            spec = schema.get("spec", {})
            if "scale" in spec:
                UNIT_SCALES.setdefault(fqn, (float(spec["scale"]), spec.get("unit", "")))
    wanted = [(p["fqn"], p["unit"], p["scale"]) for p in PARAMS.values()]
    wanted += [(f"{PARAM_FQN_PREFIX}.{n}", unit, None) for n, (_v, unit) in HOLD.items()]
    wanted += [(fqn, unit, None) for fqn, (_path, _v, unit) in CONSTANTS.items()]
    wanted += [(fqn, "ms", TOF_SCALE) for fqn, _path in filter(None, TOF_PARAM.values())]
    problems, notes = [], []
    for fqn, unit, fallback in wanted:
        if fqn not in UNIT_SCALES:
            continue                     # a missing parameter is reported by validation
        scale, exp_unit = UNIT_SCALES[fqn]
        name = fqn.rsplit(".", 1)[-1]
        if exp_unit and exp_unit != unit:
            problems.append(f"{name}: values here are in {unit!r} but the experiment's unit is "
                            f"{exp_unit!r} -- rewrite them in {exp_unit!r}")
        elif fallback is not None and not math.isclose(scale, fallback, rel_tol=1e-6):
            notes.append(f"{name}: 1 {unit or '(unitless)'} = {scale:.6g} SI in the experiment "
                         f"(fallback was {fallback:.6g}); using the experiment's value")
    return problems, notes


def prepare_units():
    """Fetch the parameter trees and adopt their unit scales. Call before building steps."""
    trees = fetch_param_trees(EXPERIMENTS)
    problems, notes = load_unit_scales(trees)
    for n in notes:
        logging.info(n)
    if problems:
        raise SystemExit("Unit mismatch, nothing submitted:\n" + "\n".join(f"  - {p}" for p in problems))
    return trees


def check(params, fqn, path, cls, what):
    # ndscan: params["instances"] = {fragment path: [FQNs of its free parameters]}
    instances = params["instances"]
    if fqn in instances.get(path, []):
        return
    at_paths = [p for p, fqns in instances.items() if fqn in fqns]
    if at_paths:
        hint = f"this FQN is free at paths {at_paths}"
    else:
        name = fqn.rsplit(".", 1)[-1]
        same_name = [f"{f} @ {p!r}" for p, fqns in instances.items()
                     for f in fqns if f.rsplit(".", 1)[-1] == name]
        if same_name:
            hint = "same name found as " + "; ".join(same_name)
        else:
            hint = (f"no free parameter called {name!r} in this experiment -- it is either "
                    f"fixed in code (override_param/bind_param) or its fragment is not built")
    raise ValueError(f"{cls}: {what} {fqn} @ {path!r} not found ({hint})")


def apply_step(tree, step, cls):
    params = copy.deepcopy(tree)
    params.setdefault("overrides", {})
    errors = []

    def attempt(fn, *args):
        try:
            fn(*args)
        except ValueError as e:
            errors.append(str(e))

    for fqn, path, value in step.overrides:
        attempt(check, params, fqn, path, cls, "override")
        params["overrides"][fqn] = [o for o in params["overrides"].get(fqn, []) if o["path"] != path]
        params["overrides"][fqn].append({"path": path, "value": value})
    for ax in step.axes:
        attempt(check, params, ax["fqn"], ax["path"], cls, "scan axis")
    # Set every scan option explicitly: experiments can ship their own scan defaults
    # (e.g. the benchmarks' num_repeats_per_point), which would otherwise leak through.
    params["scan"] = {**params.get("scan", {}), **SCAN_DEFAULTS, **step.scan, "axes": step.axes}
    params["execution_mode"] = "scan"
    if step.optimise is not None:
        params["execution_mode"] = "optimise"
        params["optimise"] = merge_optimise(params.get("optimise", {}), step.optimise)
        attempt(check_optimise, params, cls)
    if errors:
        raise ValueError("\n".join(errors))
    return params


def merge_optimise(default, new):
    """Overlay our settings on the experiment's default optimise block."""
    out = {**default, **new}
    out["objective"] = {**default.get("objective", {}), **new.get("objective", {})}
    # replace (not merge) the algorithm block, so no stale keys from another algorithm
    out["algorithm"] = dict(new.get("algorithm", default.get("algorithm", {})))
    return out


def check_optimise(params, cls):
    """Checks ndscan would otherwise only make when the experiment starts."""
    opt = params["optimise"]
    errors = []
    for p in opt["parameters"]:
        try:
            check(params, p["fqn"], p["path"], cls, "optimised parameter")
        except ValueError as e:
            errors.append(str(e))
            continue
        ptype = params["schemata"].get(p["fqn"], {}).get("type")
        if ptype not in (None, "float"):
            errors.append(f"{cls}: {p['fqn']} is {ptype}; optimisation needs float parameters")
        if not p["min"] < p["max"] or not p["min"] <= p["initial"] <= p["max"]:
            errors.append(f"{cls}: {p['fqn']}: optimisation needs min <= initial <= max, got "
                          f"min={p['min']:g}, initial={p['initial']:g}, max={p['max']:g} (SI)")
    channel = opt["objective"]["channel"]
    channels = params.get("result_channels")
    if channels is not None and channel not in channels:
        errors.append(f"{cls}: objective channel {channel!r} not found "
                      f"(saved channels: {sorted(channels)})")
    if errors:
        raise ValueError("\n".join(errors))


def make_expid(file, cls, params):
    from sipyco import pyon
    return {"file": file, "class_name": cls,
            "arguments": {"ndscan_params": pyon.encode(params)},
            "argument_defaults": {}, "repo_rev": None, "devarg_override": {},
            "log_level": logging.WARNING}


# Commands

def print_plan(steps, start):
    total = 0
    print(f"{'#':>3}  {'type':<22} {'what':<38} {'shots':>6}")
    for i, s in enumerate(steps[start:], start):
        total += s.shots
        print(f"{i:>3}  {s.kind:<22} {s.label:<38} {s.shots:>6}")
    print(f"\n{len(steps) - start} steps, {total} shots, ~{total * SHOT_PERIOD_S / 3600:.1f} h "
          f"at {SHOT_PERIOD_S:g} s/shot")


def list_params(pattern):
    trees = fetch_param_trees(EXPERIMENTS)
    for (file, cls), params in sorted(trees.items()):
        print(f"\n{cls}  ({file})")
        rows = sorted((fqn, path) for path, fqns in params["instances"].items() for fqn in fqns
                      if pattern.lower() in fqn.rsplit(".", 1)[-1].lower())
        for fqn, path in rows:
            schema = params["schemata"].get(fqn, {})
            spec = schema.get("spec", {})
            unit = f"  unit={spec.get('unit', '')!r} scale={spec['scale']:.6g}" if "scale" in spec else ""
            print(f"  {fqn}\n      path={path!r}{unit}  {schema.get('description', '')}")
        if not rows:
            print(f"  (no free parameter whose name contains {pattern!r})")


def build_expids(steps, start, trees=None):
    """Validate EVERY step before anything is submitted; report all problems at once."""
    if trees is None:
        trees = fetch_param_trees({s.kind for s in steps[start:]})
    out, problems = [], {}                   # problem message -> step indices
    for i, s in enumerate(steps[start:], start):
        file, cls = EXPERIMENTS[s.kind]
        try:
            out.append((i, s, make_expid(file, cls, apply_step(trees[(file, cls)], s, cls))))
        except ValueError as e:
            for msg in str(e).split("\n"):
                problems.setdefault(msg, []).append(i)
    if problems:
        lines = [f"  - {msg}\n      (steps {', '.join(map(str, idx))})" for msg, idx in problems.items()]
        raise SystemExit(f"Validation failed, nothing submitted. {len(problems)} problem(s):\n" + "\n".join(lines))
    return out


def submit(expids, wait):
    from sipyco.pc_rpc import Client
    scheduler = Client(MASTER, PORT, "schedule")
    log_path = Path(f"cmot_char_log_{datetime.now():%Y%m%d_%H%M%S}.csv")
    try:
        with log_path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["step", "rid", "kind", "label", "shots", "submitted", "finished"])
            for i, s, expid in expids:
                rid = scheduler.submit(PIPELINE, expid, 0, None, False)
                submitted = datetime.now().isoformat(timespec="seconds")
                print(f"[{i:>2}] RID {rid:<6} {s.kind:<22} {s.label}")
                finished = ""
                if wait:
                    while rid in scheduler.get_status():
                        time.sleep(2.0)
                    finished = datetime.now().isoformat(timespec="seconds")
                w.writerow([i, rid, s.kind, s.label, s.shots, submitted, finished])
                fh.flush()
    except KeyboardInterrupt:
        print("\nStopped submitting. Already-queued RIDs are still in the schedule "
              "(remove with Client(...,'schedule').delete(rid)).")
    finally:
        scheduler.close_rpc()
        print(f"Log: {log_path}  (full arguments are in each RID's HDF5 'expid')")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-params", metavar="SUBSTRING", help="print FQNs/paths matching SUBSTRING")
    ap.add_argument("--offline", action="store_true", help="print the plan without contacting the master")
    ap.add_argument("--dry-run", action="store_true", help="build and validate everything, submit nothing")
    ap.add_argument("--wait", action="store_true", help="wait for each step before submitting the next")
    ap.add_argument("--start-at", type=int, default=0, help="skip steps before this index")
    opts = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if opts.list_params is not None:
        return list_params(opts.list_params)

    global ALLOW_PLACEHOLDERS
    ALLOW_PLACEHOLDERS = opts.offline
    trees = None if opts.offline else prepare_units()   # unit scales before any value is built
    steps = build_steps()
    print_plan(steps, opts.start_at)
    if opts.offline:
        return
    expids = build_expids(steps, opts.start_at, trees)
    if opts.dry_run:
        print(f"\nDry run OK: {len(expids)} steps validated against the parameter tree.")
        return
    submit(expids, opts.wait)


if __name__ == "__main__":
    sys.exit(main())
