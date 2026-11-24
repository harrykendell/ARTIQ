#!/usr/bin/env python3
"""
Submit the PGC optimisation experiment to the ARTIQ master as ndscan experiments:
five Bayesian optimisations (Opt_A .. Opt_E), all imaged after PGC, interleaved
with PGC benchmark thermometry and benchmark shots at the run-sheet defaults.

    thermometry_0 -> Opt_A -> shot -> Opt_B -> shot -> Opt_C ->
    thermometry_1 -> Opt_D -> shot -> Opt_E -> thermometry_2

Every step starts from the experiment's full ndscan parameter tree (read from
experiment_db), adds overrides, and is validated against the tree BEFORE anything
is submitted. Values are written in the GUI's display units; the conversion to SI
is read from each experiment's own parameter schema.

Usage
-----
    python pgc_opt.py --offline               # print the plan, no master needed
    python pgc_opt.py --dry-run               # build + validate against master, submit nothing
    python pgc_opt.py --smoke                 # tiny version of every step (~4 min), PASS/FAIL each
    python pgc_opt.py --wait                  # the real experiment, one step at a time
    python pgc_opt.py --wait --start-at 5     # resume from step 5
    python pgc_opt.py --list-params magnif    # list parameters whose name contains "magnif"
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
BENCH = ("repository/benchmark/benchmark.py", "PGCCharBench")    # PGCBench with LOADING_TIME = 5 s
EXPERIMENTS = {
    "benchmark_thermometry": BENCH,
    "benchmark_shot":        ABS_IMAGE,
    "optimise":              ABS_IMAGE,   # ndscan execution_mode = "optimise"
}


# Parameters, in the GUI's display units (run-sheet tables)
PARAM_FQN_PREFIX, PARAM_PATH = "repository.fragments.mot.MOT", "MOT"
GAMMA_HZ = 6.0666e6       # Γ/2π, Hz -- fallback only; the experiment's own scale is used

# default = held value (and the optimiser's reference/start point); lo/hi = search range
CMOT = {
    "CMOT_detuning":           dict(default=9.65,  lo=6.0,  hi=12.0,  scale=GAMMA_HZ, unit="Γ"),
    "CMOT_duration":           dict(default=4.0,   lo=0.5,  hi=10.0,  scale=1e-3, unit="ms"),
    "CMOT_settle_time":        dict(default=3.79,  lo=1.5,  hi=10.0,  scale=1e-3, unit="ms"),
    "CMOT_repump_detuning":    dict(default=0.075, lo=0.0,  hi=5.0,   scale=GAMMA_HZ, unit="Γ"),
    "CMOT_repump_attenuation": dict(default=3.09,  lo=0.0,  hi=5.0,   scale=1.0,  unit="dB"),
    "CMOT_Y_current":          dict(default=0.84,  lo=0.5,  hi=5.0,   scale=1e-3, unit="mA"),
    "CMOT_Z_current":          dict(default=59.8,  lo=10.0, hi=100.0, scale=1e-3, unit="mA"),
}
PGC = {
    "PGC_detuning":            dict(default=16.0,  lo=14.0, hi=19.0,  scale=GAMMA_HZ, unit="Γ"),
    "PGC_duration":            dict(default=8.0,   lo=4.0,  hi=12.0,  scale=1e-3, unit="ms"),
    "PGC_settle_time":         dict(default=1.0,   lo=0.5,  hi=5.0,   scale=1e-3, unit="ms"),
    "PGC_repump_detuning":     dict(default=0.0,   lo=0.0,  hi=5.0,   scale=GAMMA_HZ, unit="Γ"),
    "PGC_repump_attenuation":  dict(default=0.05,  lo=0.0,  hi=5.0,   scale=1.0,  unit="dB"),
    "PGC_Y_current":           dict(default=0.32,  lo=0.2,  hi=5.0,   scale=1e-3, unit="mA"),
    "PGC_Z_current":           dict(default=60.0,  lo=10.0, hi=100.0, scale=1e-3, unit="mA"),
}
PARAMS = {**CMOT, **PGC}
for _name, _p in PARAMS.items():
    _p.setdefault("fqn", f"{PARAM_FQN_PREFIX}.{_name}")
    _p.setdefault("path", PARAM_PATH)


# The optimisations

# cmot: True = CMOT and PGC stages both run; False = PGC only (CMOT skipped).
# params: optimised parameters; every other parameter is held at its default.
# settings: per-optimisation changes to OPTIMISE.
#
# Fixed budget for comparing dimensionalities: every run has the same max_evals
# (OPTIMISE below), and n_init is chosen per run so that every run starts from
# ~40 Latin-hypercube points. BayesianOptimizer uses int(n_init * sqrt(d)) start
# points for d >= 3 parameters, but d * n_init for d = 1 or 2.
def _start(n_init):
    return {"algorithm": {"n_init": n_init}}


OPTIMISATIONS = {
    "Opt_A": dict(cmot=True,  params=list(CMOT) + list(PGC), settings=_start(11)),    # 41 start points
    "Opt_B": dict(cmot=True,  params=["CMOT_Z_current", "CMOT_detuning", "CMOT_settle_time",
                                      "CMOT_duration", "PGC_Z_current", "PGC_detuning",
                                      "PGC_duration"], settings=_start(15)),           # 39
    "Opt_C": dict(cmot=False, params=list(PGC), settings=_start(15)),                  # 39
    "Opt_D": dict(cmot=False, params=["PGC_Z_current", "PGC_repump_attenuation",
                                      "PGC_detuning", "PGC_duration"], settings=_start(20)),  # 40
    "Opt_E": dict(cmot=False, params=["PGC_Z_current", "PGC_duration"], settings=_start(20)), # 40
}

# ndscan optimise block (ndscan/experiment/optimize.py), shared by all five.
OPTIMISE = {
    "objective": {"channel": "custom_objective", "direction": "min"},
    "algorithm": {
        "kind": "bayesian",          # "Bayesian optimization" in the GUI
        "n_init": 10,                # default only: each run sets its own in OPTIMISATIONS
        "user_seed": -1,
        # Convergence (needs the updated bayesian.py with conv_delay and ei_fraction):
        # stop when, for `conv_delay` iterations, the model's predicted best has changed
        # by less than one point's measurement noise (or fatol, if larger), moved less
        # than xatol of each parameter's range, and no point is expected to beat it by
        # more than ei_fraction of that noise. Unpatched ndscan ignores the last two.
        "xatol": 0.05,
        "fatol": 1e-3,
        "conv_delay": 15,
        "ei_fraction": 0.1,
    },
    "num_repeats_per_point": 3,      # 3 shots per point, averaged
    "averaging_method": "mean",
    "max_evals": 600,                # SHOTS incl. references (~180 candidates); an upper limit
                                     # once convergence stops a run early
    "reference_normalisation": "subtract",
    "reference_resample_interval": 10,   # re-measure the defaults every 10 candidates
    "skip_on_persistent_transitory_error": False,
}


# Imaging and sequence settings, common to every step

TOF_SINGLE_MS = 25.0                                      # imaging after PGC
TOF_BENCH_THERM_MS = [8.0, 11.0, 14.0, 17.0, 20.0, 23.0, 26.0, 29.0, 32.0]  # = PGC_TOF_TIMES
BENCH_THERM_REPEATS, BENCH_SHOT_REPEATS = 3, 3
BENCH_REPEAT_KEY = "num_repeats"     # or "num_repeats_per_point" for back-to-back shots

# Expansion time lives on each experiment's top-level fragment: (fqn, path).
TOF_PARAM = {
    ABS_IMAGE: ("absorption_image.AbsorptionImageExpFrag.expansion_time", ""),
    BENCH:     ("benchmark.PGCCharBenchFragment.expansion_time", ""),
}
TOF_SCALE = 1e-3

# Imaging settings on the same top-level fragment as the expansion time, so their
# FQN is "<that fragment>.<name>" in each experiment: name -> (value, unit, fallback scale)
IMAGING = {
    "exposure_time": (0.03, "ms", 1e-3),
    "magnification": (0.227, "", 1.0),        # name and unit unconfirmed: --list-params magnif
}

# Run-sheet constants pinned on every step: fqn -> (path, value, unit)
CONSTANTS = {
    "repository.fragments.mot.MOT.MOT_loading_gradient": ("MOT", 0.8, "A"),
}

# MOT loading time. PGCCharBench fixes its own (5 s) in benchmark.py.
LOADING_TIME_S = 5.0

# Sequence flags. PGCCharBench fixes these itself; AbsorptionImage leaves them free.
_AI = "absorption_image.AbsorptionImageExpFrag"
SEQUENCE = {
    ABS_IMAGE: [
        (f"{_AI}.do_pgc",           "", True),
        (f"{_AI}.trap_frequency",   "", False),
        (f"{_AI}.ODT_active",       "", False),
        (f"{_AI}.do_evaporation1",  "", False),
        (f"{_AI}.do_evaporation2",  "", False),
        ("repository.fragments.mot.MOT.loading_time", "MOT", LOADING_TIME_S),
    ],
    BENCH: [],
}
DO_CMOT = f"{_AI}.do_cmot"            # set per step on AbsorptionImage

SCAN_DEFAULTS = {
    "num_repeats": 1,
    "num_repeats_per_point": 1,
    "randomise_order_globally": False,
    "no_axes_mode": "single",
    "skip_on_persistent_transitory_error": False,
}

SHOT_PERIOD_S = 6.0                   # only used for the time estimate



# Step description and builders

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


def to_si(fqn, value, fallback_scale):
    """GUI display value -> SI value ndscan stores, using the experiment's own scale."""
    return float(value) * UNIT_SCALES.get(fqn, (fallback_scale,))[0]


def si(key, v):
    return to_si(PARAMS[key]["fqn"], v, PARAMS[key]["scale"])


def top_fragment(kind):
    fqn, path = TOF_PARAM[EXPERIMENTS[kind]]
    return fqn.rsplit(".", 1)[0], path


def base_overrides(kind, exclude=()):
    """Sequence flags, imaging settings, constants and every parameter at its default."""
    exp = EXPERIMENTS[kind]
    frag, frag_path = top_fragment(kind)
    ov = list(SEQUENCE[exp])
    ov += [(f"{frag}.{n}", frag_path, to_si(f"{frag}.{n}", v, s)) for n, (v, _u, s) in IMAGING.items()]
    ov += [(fqn, path, to_si(fqn, v, 1.0)) for fqn, (path, v, _u) in CONSTANTS.items()]
    ov += [(p["fqn"], p["path"], si(k, p["default"])) for k, p in PARAMS.items() if k not in exclude]
    return ov


def tof_axis(kind, tofs_ms):
    fqn, path = TOF_PARAM[EXPERIMENTS[kind]]
    return {"type": "list", "fqn": fqn, "path": path,
            "range": {"values": [to_si(fqn, t, TOF_SCALE) for t in tofs_ms], "randomise_order": False}}


def tof_override(kind, tof_ms):
    fqn, path = TOF_PARAM[EXPERIMENTS[kind]]
    return [(fqn, path, to_si(fqn, tof_ms, TOF_SCALE))]


def benchmark_thermometry(name):
    return Step("benchmark_thermometry", f"{name}: PGC defaults, TOF scan",
                len(TOF_BENCH_THERM_MS) * BENCH_THERM_REPEATS,
                overrides=base_overrides("benchmark_thermometry"),
                axes=[tof_axis("benchmark_thermometry", TOF_BENCH_THERM_MS)],
                scan={BENCH_REPEAT_KEY: BENCH_THERM_REPEATS})


def benchmark_shot():
    # one-point TOF axis so the repeats apply and the TOF is recorded with the data
    return Step("benchmark_shot", f"PGC defaults @ {TOF_SINGLE_MS:g} ms", BENCH_SHOT_REPEATS,
                overrides=base_overrides("benchmark_shot") + [(DO_CMOT, "", True)],
                axes=[tof_axis("benchmark_shot", [TOF_SINGLE_MS])],
                scan={"num_repeats": BENCH_SHOT_REPEATS})


def lhs_points(n_params, n_init):
    """Start points BayesianOptimizer draws (its __init__): sqrt scaling only from d = 3."""
    return int(n_init * math.sqrt(n_params)) if n_params >= 3 else n_params * n_init


def optimisation(name):
    o = OPTIMISATIONS[name]
    names = o["params"]
    unknown = [k for k in names if k not in PARAMS]
    if unknown:
        raise SystemExit(f"{name}: unknown parameters {unknown}")
    parameters = [dict(fqn=PARAMS[k]["fqn"], path=PARAMS[k]["path"],
                       min=si(k, PARAMS[k]["lo"]), max=si(k, PARAMS[k]["hi"]),
                       initial=si(k, PARAMS[k]["default"])) for k in names]
    settings = {**OPTIMISE, **o.get("settings", {})}
    settings["algorithm"] = {**OPTIMISE["algorithm"], **o.get("settings", {}).get("algorithm", {})}
    ov = (base_overrides("optimise", exclude=names) + [(DO_CMOT, "", o["cmot"])]
          + tof_override("optimise", TOF_SINGLE_MS))
    stages = "CMOT+PGC" if o["cmot"] else "PGC only"
    return Step("optimise", f"{name}: {len(names)} params, {stages}", settings["max_evals"],
                overrides=ov, optimise={**settings, "parameters": parameters})


def build_steps():
    return [
        benchmark_thermometry("thermometry_0"),
        optimisation("Opt_A"),
        benchmark_shot(),
        optimisation("Opt_B"),
        benchmark_shot(),
        optimisation("Opt_C"),
        benchmark_thermometry("thermometry_1"),
        optimisation("Opt_D"),
        benchmark_shot(),
        optimisation("Opt_E"),
        benchmark_thermometry("thermometry_2"),
    ]


def shrink_for_smoke():
    """Tiny version of every step: each optimisation still runs its own stages and
    parameters and n_init, but with 6 shots, 1 shot per point and a reference every 2 points."""
    global TOF_BENCH_THERM_MS, BENCH_THERM_REPEATS, BENCH_SHOT_REPEATS
    TOF_BENCH_THERM_MS = [TOF_BENCH_THERM_MS[len(TOF_BENCH_THERM_MS) // 2], TOF_BENCH_THERM_MS[-1]]
    BENCH_THERM_REPEATS, BENCH_SHOT_REPEATS = 1, 1
    small = dict(num_repeats_per_point=1, max_evals=6, reference_resample_interval=2)
    OPTIMISE.update(small)
    for o in OPTIMISATIONS.values():          # keep each run's n_init, shrink the rest
        for k in small:
            o.get("settings", {}).pop(k, None)
    return [
        benchmark_thermometry("thermometry"),
        benchmark_shot(),
        *[optimisation(n) for n in OPTIMISATIONS],
    ]



# ndscan parameter tree: fetch, units, validate, apply
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
    check them against the units the values here are written in."""
    UNIT_SCALES.clear()
    for params in trees.values():
        for fqn, schema in params["schemata"].items():
            spec = schema.get("spec", {})
            if "scale" in spec:
                UNIT_SCALES.setdefault(fqn, (float(spec["scale"]), spec.get("unit", "")))
    wanted = [(p["fqn"], p["unit"], p["scale"]) for p in PARAMS.values()]
    wanted += [(fqn, unit, None) for fqn, (_path, _v, unit) in CONSTANTS.items()]
    for fqn, _path in TOF_PARAM.values():
        frag = fqn.rsplit(".", 1)[0]
        wanted.append((fqn, "ms", TOF_SCALE))
        wanted += [(f"{frag}.{n}", unit, s) for n, (_v, unit, s) in IMAGING.items()]
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
    return problems, sorted(set(notes))


def prepare_units():
    """Fetch the parameter trees and adopt their unit scales. Call before building steps."""
    trees = fetch_param_trees(EXPERIMENTS)
    problems, notes = load_unit_scales(trees)
    for n in notes:
        logging.info(n)
    if problems:
        raise SystemExit("Unit mismatch, nothing submitted:\n"
                         + "\n".join(f"  - {p}" for p in sorted(set(problems))))
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
    # every scan option explicit, so no experiment's own scan defaults leak through
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


def build_expids(steps, start, trees):
    """Validate EVERY step before anything is submitted; report all problems at once."""
    out, problems = [], {}
    for i, s in enumerate(steps[start:], start):
        file, cls = EXPERIMENTS[s.kind]
        try:
            out.append((i, s, make_expid(file, cls, apply_step(trees[(file, cls)], s, cls))))
        except ValueError as e:
            for msg in str(e).split("\n"):
                problems.setdefault(msg, []).append(i)
    if problems:
        lines = [f"  - {msg}\n      (steps {', '.join(map(str, idx))})" for msg, idx in problems.items()]
        raise SystemExit(f"Validation failed, nothing submitted. {len(problems)} problem(s):\n"
                         + "\n".join(lines))
    return out



# Commands

def print_plan(steps, start):
    total = 0
    print(f"{'#':>3}  {'type':<22} {'what':<38} {'shots':>6}  note")
    for i, s in enumerate(steps[start:], start):
        total += s.shots
        note = ""
        if s.optimise is not None:
            n = len(s.optimise["parameters"])
            n_init = s.optimise["algorithm"]["n_init"]
            note = f"n_init={n_init}: {lhs_points(n, n_init)} LHS start points"
        print(f"{i:>3}  {s.kind:<22} {s.label:<38} {s.shots:>6}  {note}")
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


def submit(expids, wait, log_name="pgc_opt_log"):
    from sipyco.pc_rpc import Client
    scheduler = Client(MASTER, PORT, "schedule")
    log_path = Path(f"{log_name}_{datetime.now():%Y%m%d_%H%M%S}.csv")
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


def run_smoke(expids, timeout_s=900):
    """Run each tiny step, wait for it, and judge it from the datasets ndscan writes."""
    from sipyco.pc_rpc import Client
    scheduler = Client(MASTER, PORT, "schedule")
    datasets = Client(MASTER, PORT, "dataset_db")

    def get(key):
        try:
            return datasets.get(key)
        except Exception:
            return None

    results = []
    try:
        for i, step, expid in expids:
            rid = scheduler.submit(PIPELINE, expid, 0, None, False)
            print(f"\n[{i}] RID {rid}  {step.label}")
            t0 = time.monotonic()
            while rid in scheduler.get_status():
                if time.monotonic() - t0 > timeout_s:
                    scheduler.request_termination(rid)
                    break
                time.sleep(1.0)
            pre = f"ndscan.rid_{rid}."
            completed, mode = get(pre + "completed"), get(pre + "execution_mode")
            n_points = len(get(pre + "points.axis_0") or [])
            if completed is None:
                ok, msg = False, "never started: build/prepare failed (see the master log)"
            elif not completed:
                ok, msg = False, "started but did not complete (see the master log)"
            elif step.optimise is not None:
                reason = get(pre + "optimizer.termination_reason")
                ok = mode == "optimise" and n_points > 0
                msg = f"mode={mode}, {n_points} points, termination={reason!r}"
            else:
                ok = mode == "scan" and n_points == step.shots
                msg = f"mode={mode}, {n_points}/{step.shots} points"
            print(f"    {'PASS' if ok else 'FAIL'}: {msg}")
            results.append((rid, step, ok, msg))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        scheduler.close_rpc()
        datasets.close_rpc()
    print("\n" + "=" * 72)
    for rid, step, ok, msg in results:
        print(f"  {'PASS' if ok else 'FAIL'}  RID {rid:<7} {step.label:<36} {msg}")
    n_pass = sum(r[2] for r in results)
    print(f"{n_pass}/{len(expids)} steps passed")
    return 0 if n_pass == len(expids) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-params", metavar="SUBSTRING", help="list parameters whose name contains SUBSTRING")
    ap.add_argument("--offline", action="store_true", help="print the plan without contacting the master")
    ap.add_argument("--dry-run", action="store_true", help="build and validate everything, submit nothing")
    ap.add_argument("--smoke", action="store_true", help="run a tiny version of every step and check each")
    ap.add_argument("--wait", action="store_true", help="wait for each step before submitting the next")
    ap.add_argument("--start-at", type=int, default=0, help="skip steps before this index")
    opts = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if opts.list_params is not None:
        return list_params(opts.list_params)

    trees = None if opts.offline else prepare_units()   # unit scales before any value is built
    steps = shrink_for_smoke() if opts.smoke else build_steps()
    if opts.smoke:
        print("Smoke test: tiny version of every step\n")
    print_plan(steps, opts.start_at)
    if opts.offline:
        return 0
    expids = build_expids(steps, opts.start_at, trees)
    if opts.dry_run:
        print(f"\nDry run OK: {len(expids)} steps validated against the parameter tree.")
        return 0
    if opts.smoke:
        return run_smoke(expids)
    submit(expids, opts.wait)
    return 0


if __name__ == "__main__":
    sys.exit(main())
