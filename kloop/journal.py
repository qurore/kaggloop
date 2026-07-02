"""Append-only decision journal — the project's observability / audit trail.

Every *major decision* in a project is logged here, so a human can later open one
file and reconstruct exactly how the current model came to be: which competition
and why, the target and its rationale, the CV design, which hypotheses were kept
or rejected and on what evidence, the ensemble chosen, the leakage-gate outcome,
each submission, and each loop's gap analysis.

The journal is **append-only**:
  * this module only ever appends (it never rewrites the file), and
  * the PreToolUse guard blocks shell that would truncate/delete it.

It is also **enforced**: ``kloop.project set --status done`` refuses to mark a
stage done unless a decision for that stage+iteration has been journaled (see
``kloop.project``).

    python -m kloop.journal log --kind decision --decision "use 5-fold GroupKFold by patient_id" \
        --rationale "leakage-safe; matches the host's per-patient split" --refs "discussion#123"
    python -m kloop.journal show [--stage experiment] [--kind hypothesis_kept] [--n 20]

``--stage`` / ``--iteration`` default to the current project state, so entries are
auto-tagged to where you are in the loop. All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import state

# Suggested decision kinds (free-form is allowed, but these keep the log skimmable).
KINDS = [
    "competition_selected", "target_set", "cv_design", "hypothesis_proposed",
    "hypothesis_kept", "hypothesis_rejected", "ensemble", "gate", "submission",
    "gap_analysis", "self_improve", "loop_decision", "decision",
]


def _resolve(name):
    n = name or state.current_project()
    if not n:
        print("No active project (pass --name).", file=sys.stderr)
        raise SystemExit(2)
    return n


def cmd_log(args) -> int:
    name = _resolve(args.name)
    st = state.load_state(name)
    rec = {
        "stage": args.stage or st.get("stage"),
        "iteration": st.get("iteration") if args.iteration is None else args.iteration,
        "kind": args.kind,
        "decision": args.decision,
        "rationale": args.rationale or "",
        "refs": [r for r in (args.refs or "").split(",") if r.strip()],
        "evidence": args.evidence or "",
    }
    out = state.append_decision(name, rec)
    print(f"decision logged: [{out['stage']}#{out['iteration']}] {out['kind']}: {out['decision']}")
    return 0


def cmd_show(args) -> int:
    name = _resolve(args.name)
    rows = state.load_decisions(name)
    if args.stage:
        rows = [r for r in rows if r.get("stage") == args.stage]
    if args.kind:
        rows = [r for r in rows if r.get("kind") == args.kind]
    rows = rows[-args.n:] if args.n else rows
    if not rows:
        print("(no decision log yet)")
        return 0
    for r in rows:
        refs = ("  refs=" + ",".join(r.get("refs", []))) if r.get("refs") else ""
        print(f"{r.get('ts')}  [{r.get('stage')}#{r.get('iteration')}] "
              f"{r.get('kind')}: {r.get('decision')}")
        if r.get("rationale"):
            print(f"    └ {r['rationale']}{refs}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.journal")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("log", help="append a decision to the journal")
    pl.add_argument("--name", default=None)
    pl.add_argument("--kind", default="decision",
                    help="e.g. " + ", ".join(KINDS))
    pl.add_argument("--decision", required=True, help="the decision, in one line")
    pl.add_argument("--rationale", default="", help="why (evidence-based)")
    pl.add_argument("--refs", default="", help="comma-separated references (notebook/discussion/paper/file)")
    pl.add_argument("--evidence", default="", help="pointer to the file/metric backing this")
    pl.add_argument("--stage", default=None, help="defaults to the project's current stage")
    pl.add_argument("--iteration", type=int, default=None, help="defaults to the current iteration")
    pl.set_defaults(func=cmd_log)

    ps = sub.add_parser("show", help="read the decision journal")
    ps.add_argument("--name", default=None)
    ps.add_argument("--stage", default=None)
    ps.add_argument("--kind", default=None)
    ps.add_argument("--n", type=int, default=0, help="show only the last N entries")
    ps.set_defaults(func=cmd_show)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
