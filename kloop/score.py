"""Local cross-validation and ensembling helpers.

Most heavy lifting happens on Colab, but the agent often needs to combine
out-of-fold (OOF) predictions from several Colab jobs locally to decide what to
ensemble before the final submission. These helpers cover the small, generic
mechanics: a metric registry, OOF blending (mean / weighted / rank), and a
greedy blend search.

numpy / scikit-learn are imported lazily so this module loads even where they're
absent; the helpers raise a clear message telling you to run
``scripts/setup.sh`` if a dependency is missing.

All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _np():
    try:
        import numpy as np  # noqa
        return np
    except ImportError:
        print("numpy is required. Run `bash scripts/setup.sh`.",
              file=sys.stderr)
        raise SystemExit(3)


def _sklearn_metrics():
    try:
        from sklearn import metrics  # noqa
        return metrics
    except ImportError:
        print("scikit-learn is required. Run `bash scripts/setup.sh`.",
              file=sys.stderr)
        raise SystemExit(3)


# (function(y_true, y_pred) -> float, direction). "pred" may be probabilities or
# labels depending on the metric, as in the matching Kaggle competition.
def _metric_fns():
    m = _sklearn_metrics()
    np = _np()
    return {
        "rmse": (lambda yt, yp: float(np.sqrt(m.mean_squared_error(yt, yp))), "minimize"),
        "mse": (lambda yt, yp: float(m.mean_squared_error(yt, yp)), "minimize"),
        "mae": (lambda yt, yp: float(m.mean_absolute_error(yt, yp)), "minimize"),
        "rmsle": (lambda yt, yp: float(np.sqrt(m.mean_squared_log_error(yt, yp))), "minimize"),
        "logloss": (lambda yt, yp: float(m.log_loss(yt, yp)), "minimize"),
        "auc": (lambda yt, yp: float(m.roc_auc_score(yt, yp)), "maximize"),
        "accuracy": (lambda yt, yp: float(m.accuracy_score(yt, yp)), "maximize"),
        "f1": (lambda yt, yp: float(m.f1_score(yt, yp)), "maximize"),
        "f1_macro": (lambda yt, yp: float(m.f1_score(yt, yp, average="macro")), "maximize"),
        "r2": (lambda yt, yp: float(m.r2_score(yt, yp)), "maximize"),
    }


def metric_names() -> list[str]:
    return list(_metric_fns().keys())


def score(metric: str, y_true, y_pred) -> float:
    fns = _metric_fns()
    if metric not in fns:
        raise KeyError(f"unknown metric {metric!r}; known: {', '.join(fns)}")
    fn, _ = fns[metric]
    return fn(y_true, y_pred)


def direction(metric: str) -> str:
    return _metric_fns()[metric][1]


def _load_array(path: str):
    np = _np()
    p = Path(path)
    if p.suffix == ".npy":
        return np.load(p)
    if p.suffix in (".csv", ".txt"):
        return np.loadtxt(p, delimiter="," if p.suffix == ".csv" else None)
    raise ValueError(f"unsupported array file: {path}")


def blend(preds: list, weights: list | None = None, rank: bool = False):
    """Weighted (optionally rank-transformed) average of OOF/test predictions."""
    np = _np()
    arrs = [np.asarray(p, dtype=float) for p in preds]
    if rank:
        def _rankt(a):
            order = a.argsort()
            r = np.empty_like(order, dtype=float)
            r[order] = np.arange(len(a))
            return r / max(len(a) - 1, 1)
        arrs = [_rankt(a) for a in arrs]
    if weights is None:
        weights = [1.0] * len(arrs)
    w = np.asarray(weights, dtype=float)
    w = w / w.sum()
    return sum(wi * ai for wi, ai in zip(w, arrs))


def greedy_blend(metric: str, y_true, oofs: dict, n_steps: int = 50):
    """Greedy forward selection over OOF predictions (Caruana-style ensembling).

    ``oofs`` maps model name -> OOF prediction array. Returns (weights, score).
    """
    np = _np()
    fn, direc = _metric_fns()[metric]
    names = list(oofs.keys())
    mats = {k: np.asarray(v, dtype=float) for k, v in oofs.items()}
    yt = np.asarray(y_true)
    better = (lambda a, b: a > b) if direc == "maximize" else (lambda a, b: a < b)

    chosen: list[str] = []
    cur_sum = None
    best_score = None
    for _ in range(n_steps):
        step_best, step_name, step_pred = None, None, None
        for k in names:
            cand = mats[k] if cur_sum is None else (cur_sum + mats[k])
            pred = cand / (len(chosen) + 1)
            s = fn(yt, pred)
            if step_best is None or better(s, step_best):
                step_best, step_name, step_pred = s, k, cand
        if best_score is not None and not better(step_best, best_score):
            break
        best_score, cur_sum = step_best, step_pred
        chosen.append(step_name)

    weights = {k: chosen.count(k) / len(chosen) for k in set(chosen)} if chosen else {}
    return weights, best_score


# --------------------------------------------------------------------------- CLI

def cmd_metrics(args) -> int:
    print("Available metrics:")
    for n in metric_names():
        print(f"  {n:10s} ({direction(n)})")
    return 0


def cmd_score(args) -> int:
    yt = _load_array(args.y_true)
    yp = _load_array(args.y_pred)
    s = score(args.metric, yt, yp)
    print(json.dumps({"metric": args.metric, "score": s,
                      "direction": direction(args.metric)}, ensure_ascii=False))
    return 0


def cmd_blend(args) -> int:
    arrs = [_load_array(p) for p in args.preds]
    weights = [float(w) for w in args.weights] if args.weights else None
    out = blend(arrs, weights, rank=args.rank)
    _np().save(args.out, out)
    print(f"blend saved: {args.out}  (shape={out.shape})")
    if args.metric and args.y_true:
        s = score(args.metric, _load_array(args.y_true), out)
        print(json.dumps({"metric": args.metric, "blend_score": s}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.score")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("metrics", help="list available metrics")
    pm.set_defaults(func=cmd_metrics)

    psc = sub.add_parser("score", help="score predictions against ground truth")
    psc.add_argument("--metric", required=True)
    psc.add_argument("--y-true", dest="y_true", required=True)
    psc.add_argument("--y-pred", dest="y_pred", required=True)
    psc.set_defaults(func=cmd_score)

    pb = sub.add_parser("blend", help="blend several prediction files")
    pb.add_argument("preds", nargs="+", help="prediction array files (.npy/.csv)")
    pb.add_argument("--weights", nargs="*", default=None)
    pb.add_argument("--rank", action="store_true", help="rank-transform before averaging")
    pb.add_argument("--out", required=True)
    pb.add_argument("--metric", default="")
    pb.add_argument("--y-true", dest="y_true", default="")
    pb.set_defaults(func=cmd_blend)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
