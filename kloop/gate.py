"""Data-leakage quality gate — a strict, Kaggle-specific guard rail.

Leakage (test info bleeding into training/CV, target leakage, group/time
contamination) is the classic way a Kaggle pipeline gets a great CV that
collapses on the private leaderboard. This module is a **hard gate**: an
experiment's CV is not to be trusted, and nothing is to be submitted, until the
gate passes.

The gate has two halves:

1. **Automated checks** (`check`) — concrete, data-driven detectors that need
   real inputs (so you can't pass them by hand-waving):
     - train/test id overlap (identity leakage)
     - OOF sanity: NaNs, shape, and *implausibly perfect* CV
     - single-feature target leakage (a lone feature that predicts the target
       almost perfectly)
     - group-fold integrity (a group/entity spanning train and validation folds)
     - time-fold integrity (validation rows from before the training cutoff)
     - CV↔LB consistency (a soft signal: CV far better than realized LB)

2. **A declarative checklist** (`affirm`) — leakage-safety facts that can't be
   auto-detected and must be explicitly affirmed by the agent:
   feature transforms fit on train only, out-of-fold target encoding, no future
   info, no host-prohibited external data/leaks, CV matches the competition split.

`verify` requires **zero automated failures**, **no mandatory check skipped**, and
**every checklist item affirmed**; only then does it write a passing
``gate.json`` (and set ``gate_passed`` in state) — which the submission guard hook
checks before allowing a Kaggle submit. All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import state

# Checklist the agent must affirm (key -> human statement). All are mandatory.
CHECKLIST = {
    "fit_on_train_only": "All feature transforms (scaling/encoding/imputation) are fit on train only and applied to test",
    "oof_target_encoding": "Target-encoding / aggregate features are computed out-of-fold within CV, not leaked across all train",
    "no_future_info": "(time series) No future information is included in the features",
    "no_banned_external": "No competition-banned external data or leakage is used",
    "cv_matches_split": "The CV design matches the competition's train/test split (group/time/stratify)",
    "no_test_in_train": "No test rows leak into train, and there is no label leak from id/ordering",
}
# Automated checks that MUST run (not be skipped) for a pass.
MANDATORY_CHECKS = {"train_test_overlap", "oof_sanity"}


def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        print("numpy is required. Run `bash scripts/setup.sh`.", file=sys.stderr)
        raise SystemExit(3)


def _load_1d(spec: str):
    """Load a 1-D array from 'file' or 'file:column' (.npy / .csv)."""
    np = _np()
    if ":" in spec and not spec.endswith(".npy"):
        path, col = spec.rsplit(":", 1)
    else:
        path, col = spec, None
    p = Path(path)
    if p.suffix == ".npy":
        return np.load(p, allow_pickle=True).ravel()
    import csv
    rows = list(csv.reader(p.open()))
    header = rows[0]
    idx = header.index(col) if col else 0
    return np.array([r[idx] for r in rows[1:]], dtype=object)


def _load_2d(path: str):
    np = _np()
    p = Path(path)
    if p.suffix == ".npy":
        return np.load(p), None
    try:
        import pandas as pd
        df = pd.read_csv(p)
        return df.values, list(df.columns)
    except ImportError:
        arr = np.genfromtxt(p, delimiter=",", names=True)
        return arr, None


def _result(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


# --------------------------------------------------------------------------- checks

def chk_train_test_overlap(train_ids, test_ids):
    np = _np()
    tr = set(map(str, np.asarray(train_ids).ravel().tolist()))
    te = set(map(str, np.asarray(test_ids).ravel().tolist()))
    inter = tr & te
    if inter:
        sample = list(inter)[:5]
        return _result("train_test_overlap", "fail",
                       f"{len(inter)} shared id(s) between train and test (e.g. {sample}) -> identity leakage")
    return _result("train_test_overlap", "pass", "no id overlap between train/test")


def chk_oof_sanity(y_true, oof, task, metric):
    np = _np()
    yt = np.asarray(y_true, dtype=float).ravel()
    yp = np.asarray(oof, dtype=float).ravel()
    if yt.shape != yp.shape:
        return _result("oof_sanity", "fail", f"shape mismatch y_true{yt.shape} vs oof{yp.shape}")
    if np.isnan(yp).any():
        return _result("oof_sanity", "fail", "OOF predictions contain NaN")
    try:
        if task == "classification":
            from sklearn.metrics import roc_auc_score, accuracy_score
            if len(np.unique(yt)) == 2:
                s = float(roc_auc_score(yt, yp))
                name = "AUC"
            else:
                s = float(accuracy_score(yt, (yp >= 0.5).astype(int)))
                name = "acc"
        else:
            ss_res = float(((yt - yp) ** 2).sum())
            ss_tot = float(((yt - yt.mean()) ** 2).sum()) or 1e-12
            s = 1.0 - ss_res / ss_tot
            name = "R2"
    except Exception as e:  # noqa: BLE001 — sanity check must not crash the gate
        return _result("oof_sanity", "warn", f"scoring failed ({e}); manual check recommended")
    if s >= 0.9999:
        return _result("oof_sanity", "fail",
                       f"OOF {name}={s:.5f} is near-perfect -> almost certainly leakage")
    if s >= 0.99:
        return _result("oof_sanity", "warn", f"OOF {name}={s:.5f} is very high; check for leakage")
    return _result("oof_sanity", "pass", f"OOF {name}={s:.5f} (plausible range)")


def chk_single_feature_leak(X, y, task, fail_thr=0.999, warn_thr=0.97):
    np = _np()
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float).ravel()
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    best, best_j = 0.0, -1
    binary = task == "classification" and len(np.unique(y)) == 2
    for j in range(X.shape[1]):
        col = X[:, j]
        if np.isnan(col).any() or np.nanstd(col) == 0:
            continue
        if binary:
            try:
                from sklearn.metrics import roc_auc_score
                a = float(roc_auc_score(y, col))
                power = max(a, 1 - a)
            except Exception:
                continue
        else:
            c = np.corrcoef(col, y)[0, 1]
            power = abs(c) if c == c else 0.0  # nan-safe
        if power > best:
            best, best_j = power, j
    if best >= fail_thr:
        return _result("single_feature_leak", "fail",
                       f"single feature col[{best_j}] alone predicts the target almost perfectly (power={best:.4f}) -> suspected leak")
    if best >= warn_thr:
        return _result("single_feature_leak", "warn",
                       f"single feature col[{best_j}] has high predictive power (power={best:.4f}); check it")
    return _result("single_feature_leak", "pass", f"max single-feature power={best:.4f} (acceptable)")


def chk_group_fold_integrity(groups, folds):
    np = _np()
    g = np.asarray(groups).ravel()
    f = np.asarray(folds).ravel()
    bad = []
    for grp in set(map(str, g.tolist())):
        mask = np.array([str(x) == grp for x in g])
        if len(set(f[mask].tolist())) > 1:
            bad.append(grp)
    if bad:
        return _result("group_fold_integrity", "fail",
                       f"{len(bad)} group(s) span multiple folds (e.g. {bad[:5]}) -> group leakage")
    return _result("group_fold_integrity", "pass", "each group stays within a single fold")


def chk_time_fold_integrity(times, folds):
    np = _np()
    t = np.asarray(times, dtype=float).ravel()
    f = np.asarray(folds).ravel()
    # Order folds by their earliest timestamp; their time windows should not
    # overlap if the split respects time order (a proxy for forward-chaining CV).
    order = sorted(set(f.tolist()), key=lambda x: t[f == x].min())
    prev_max, overlaps = None, 0
    for k in order:
        cur_min, cur_max = t[f == k].min(), t[f == k].max()
        if prev_max is not None and cur_min < prev_max:
            overlaps += 1
        prev_max = cur_max
    if overlaps:
        return _result("time_fold_integrity", "warn",
                       f"fold time ranges overlap in {overlaps} place(s) -> may not be a time-based split")
    return _result("time_fold_integrity", "pass", "fold time ranges are ordered and non-overlapping")


def chk_cv_lb_consistency(cv, lb, direction, tol):
    if cv is None or lb is None:
        return _result("cv_lb_consistency", "skip", "best_cv or best_lb not set (re-evaluate after submission)")
    cv, lb = float(cv), float(lb)
    gap = (cv - lb) if direction == "maximize" else (lb - cv)
    if gap > tol:
        return _result("cv_lb_consistency", "warn",
                       f"CV is {gap:.5g} better than LB (tol={tol}); investigate leak/overfit/distribution-shift")
    return _result("cv_lb_consistency", "pass", f"CV-LB gap {gap:.5g} (within tolerance)")


# --------------------------------------------------------------------------- store

def _gate_checks_path(name):
    return state.project_dir(name) / "gate_checks.json"


def _load_checks(name) -> dict:
    p = _gate_checks_path(name)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_checks(name, data):
    data["updated"] = time.strftime("%Y-%m-%d_%H-%M-%S")
    _gate_checks_path(name).write_text(json.dumps(data, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- CLI

def _resolve(name):
    n = name or state.current_project()
    if not n:
        print("No active project (pass --name).", file=sys.stderr)
        raise SystemExit(2)
    return n


def cmd_check(args) -> int:
    name = _resolve(args.name)
    st = state.load_state(name)
    results = []

    if args.train_ids and args.test_ids:
        results.append(chk_train_test_overlap(_load_1d(args.train_ids), _load_1d(args.test_ids)))
    else:
        results.append(_result("train_test_overlap", "skip", "--train-ids/--test-ids not provided"))

    if args.oof and args.y_true:
        results.append(chk_oof_sanity(_load_1d(args.y_true), _load_1d(args.oof), args.task, st.get("metric")))
    else:
        results.append(_result("oof_sanity", "skip", "--oof/--y-true not provided"))

    if args.x and args.y_true:
        X, _ = _load_2d(args.x)
        results.append(chk_single_feature_leak(X, _load_1d(args.y_true), args.task))
    else:
        results.append(_result("single_feature_leak", "skip", "--x/--y-true not provided (skipping single-feature leak check)"))

    if args.groups and args.folds:
        results.append(chk_group_fold_integrity(_load_1d(args.groups), _load_1d(args.folds)))
    if args.time and args.folds:
        results.append(chk_time_fold_integrity(_load_1d(args.time), _load_1d(args.folds)))

    results.append(chk_cv_lb_consistency(st.get("best_cv"), st.get("best_lb"),
                                         st.get("metric_direction") or "maximize", args.cv_lb_tol))

    data = _load_checks(name)
    data["checks"] = results
    _save_checks(name, data)

    icon = {"pass": "✓", "warn": "!", "fail": "✗", "skip": "·"}
    print(f"=== leakage gate automated checks: {name} ===")
    for r in results:
        print(f"  {icon.get(r['status'], '?')} [{r['status']:4s}] {r['check']}: {r['detail']}")
    fails = [r for r in results if r["status"] == "fail"]
    print(f"--- fail={len(fails)}  warn={sum(r['status']=='warn' for r in results)} ---")
    return 1 if fails else 0


def cmd_checklist(args) -> int:
    print("=== leakage-safety checklist (affirm every item) ===")
    for k, v in CHECKLIST.items():
        print(f"  [{k}] {v}")
    print("After confirming: python -m kloop.gate affirm --confirm " + ",".join(CHECKLIST))
    return 0


def cmd_affirm(args) -> int:
    name = _resolve(args.name)
    confirmed = [k.strip() for k in (args.confirm or "").split(",") if k.strip()]
    unknown = [k for k in confirmed if k not in CHECKLIST]
    if unknown:
        print(f"unknown checklist item(s): {unknown}", file=sys.stderr)
        return 2
    data = _load_checks(name)
    data["affirmed"] = sorted(set(confirmed))
    data["affirmed_by"] = "agent"
    _save_checks(name, data)
    missing = [k for k in CHECKLIST if k not in data["affirmed"]]
    print(f"affirmed: {len(data['affirmed'])}/{len(CHECKLIST)}")
    if missing:
        print(f"  not yet affirmed: {missing}")
    return 0


def cmd_verify(args) -> int:
    name = _resolve(args.name)
    data = _load_checks(name)
    checks = data.get("checks", [])
    affirmed = set(data.get("affirmed", []))

    fails = [r["check"] for r in checks if r["status"] == "fail"]
    run = {r["check"] for r in checks}
    skipped_mandatory = [c for c in MANDATORY_CHECKS
                         if c not in run or any(r["check"] == c and r["status"] == "skip" for r in checks)]
    missing_affirm = [k for k in CHECKLIST if k not in affirmed]
    warns = [r["check"] for r in checks if r["status"] == "warn"]

    passed = not fails and not skipped_mandatory and not missing_affirm
    gate = {
        "passed": passed,
        "fails": fails,
        "skipped_mandatory": skipped_mandatory,
        "missing_affirm": missing_affirm,
        "warns": warns,
        "ts": time.strftime("%Y-%m-%d_%H-%M-%S"),
    }
    state.gate_path(name).write_text(json.dumps(gate, indent=2, ensure_ascii=False))
    # Reflect into state for the SessionStart banner.
    st = state.load_state(name)
    st["gate_passed"] = passed
    state.save_state(name, st)

    if passed:
        print(f"leakage gate PASSED: {name}" + (f" (warn: {warns})" if warns else ""))
        print("  submission is allowed (passes the submission-guard hook).")
        return 0
    print(f"leakage gate FAILED: {name}", file=sys.stderr)
    if fails:
        print(f"  failed checks: {fails}", file=sys.stderr)
    if skipped_mandatory:
        print(f"  mandatory checks not run: {skipped_mandatory} (run kloop.gate check)", file=sys.stderr)
    if missing_affirm:
        print(f"  checklist not affirmed: {missing_affirm} (kloop.gate affirm)", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.gate", description="data-leakage quality gate")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="run automated leakage detectors")
    pc.add_argument("--name", default=None)
    pc.add_argument("--train-ids", dest="train_ids", default="", help="file[:col] of train ids")
    pc.add_argument("--test-ids", dest="test_ids", default="", help="file[:col] of test ids")
    pc.add_argument("--oof", default="", help="OOF predictions (.npy/.csv)")
    pc.add_argument("--y-true", dest="y_true", default="", help="ground-truth targets (.npy/.csv)")
    pc.add_argument("--x", default="", help="feature matrix for single-feature leak test")
    pc.add_argument("--groups", default="", help="group/entity ids aligned to train")
    pc.add_argument("--folds", default="", help="fold assignment aligned to train")
    pc.add_argument("--time", default="", help="time values aligned to train")
    pc.add_argument("--task", choices=["classification", "regression"], default="classification")
    pc.add_argument("--cv-lb-tol", dest="cv_lb_tol", type=float, default=0.03)
    pc.set_defaults(func=cmd_check)

    pcl = sub.add_parser("checklist", help="print the leakage-safety checklist")
    pcl.set_defaults(func=cmd_checklist)

    pa = sub.add_parser("affirm", help="affirm checklist items (comma-separated keys)")
    pa.add_argument("--name", default=None)
    pa.add_argument("--confirm", required=True)
    pa.set_defaults(func=cmd_affirm)

    pv = sub.add_parser("verify", help="combine checks+checklist -> write gate.json")
    pv.add_argument("--name", default=None)
    pv.set_defaults(func=cmd_verify)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
