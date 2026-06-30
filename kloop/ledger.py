"""Hypothesis ledger for a kaggloop campaign.

The ledger is the heart of the win-loop: an append-only JSONL file
(``projects/<name>/hypotheses.jsonl``) where each line is one *critical-to-win*
hypothesis — a concrete, testable bet about what will move the competition
score, grounded in the dossier (top notebooks / discussions) and the academic
literature found via the science MCP servers.

The agent (in the hypothesize/experiment skills) supplies the intelligence;
this module just stores, ranks, and updates hypothesis records so the loop is
resumable and auditable.

Record schema (one JSON object per line)::

    {
      "id": "h0003",
      "title": "Pseudo-labeling on the unlabeled test set",
      "rationale": "Top notebook X + paper Y (arXiv:....) report +0.5% from ...",
      "source": "notebook|discussion|paper|insight",      # where the bet came from
      "refs": ["https://kaggle.com/...", "arXiv:2401.00000"],
      "expected_gain": 0.004,        # estimated score delta (in metric units)
      "confidence": 0.6,             # 0..1 subjective prior the bet pays off
      "effort": "M",                 # S|M|L implementation/compute cost
      "status": "proposed",          # proposed|testing|kept|rejected|blocked
      "cv_before": 0.842,
      "cv_after": 0.846,
      "lb_after": null,
      "job_id": null,                # colab job that tested it, if any
      "notes": "",
      "created": "...", "updated": "..."
    }

Ranking (``priority``) orders proposed hypotheses for testing by
``expected_gain * confidence`` discounted by effort, so the loop spends compute
on the highest expected-value bets first.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import state

EFFORT_DISCOUNT = {"S": 1.0, "M": 0.7, "L": 0.45}


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def ledger_path(run_id: str) -> Path:
    return state.project_dir(run_id) / "hypotheses.jsonl"


def load(run_id: str) -> list[dict]:
    p = ledger_path(run_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _write_all(run_id: str, rows: list[dict]) -> None:
    p = ledger_path(run_id)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _next_id(rows: list[dict]) -> str:
    n = 0
    for r in rows:
        try:
            n = max(n, int(str(r.get("id", "h0")).lstrip("h")))
        except ValueError:
            pass
    return f"h{n + 1:04d}"


def priority(row: dict) -> float:
    gain = float(row.get("expected_gain") or 0.0)
    conf = float(row.get("confidence") or 0.0)
    disc = EFFORT_DISCOUNT.get(str(row.get("effort", "M")).upper(), 0.7)
    return gain * conf * disc


def add(run_id: str, **fields) -> dict:
    rows = load(run_id)
    rec = {
        "id": _next_id(rows),
        "title": fields.get("title", ""),
        "rationale": fields.get("rationale", ""),
        "source": fields.get("source", "insight"),
        "refs": fields.get("refs", []),
        "expected_gain": fields.get("expected_gain"),
        "confidence": fields.get("confidence"),
        "effort": fields.get("effort", "M"),
        "status": fields.get("status", "proposed"),
        "cv_before": fields.get("cv_before"),
        "cv_after": fields.get("cv_after"),
        "lb_after": fields.get("lb_after"),
        "job_id": fields.get("job_id"),
        "notes": fields.get("notes", ""),
        "created": _stamp(),
        "updated": _stamp(),
    }
    rows.append(rec)
    _write_all(run_id, rows)
    return rec


def update(run_id: str, hyp_id: str, **fields) -> dict:
    rows = load(run_id)
    target = None
    for r in rows:
        if r.get("id") == hyp_id:
            target = r
            break
    if target is None:
        raise KeyError(f"hypothesis {hyp_id!r} not found in project {run_id}")
    for k, v in fields.items():
        if v is not None:
            target[k] = v
    target["updated"] = _stamp()
    _write_all(run_id, rows)
    return target


# --------------------------------------------------------------------------- CLI

def _resolve(run_id):
    rid = run_id or state.current_project()
    if not rid:
        print("アクティブなプロジェクトがありません（--name を指定してください）", file=sys.stderr)
        raise SystemExit(2)
    return rid


def cmd_add(args) -> int:
    rid = _resolve(args.name)
    refs = [r for r in (args.refs or "").split(",") if r.strip()]
    rec = add(
        rid,
        title=args.title,
        rationale=args.rationale or "",
        source=args.source,
        refs=refs,
        expected_gain=args.expected_gain,
        confidence=args.confidence,
        effort=args.effort,
    )
    print(json.dumps(rec, indent=2, ensure_ascii=False))
    return 0


def cmd_update(args) -> int:
    rid = _resolve(args.name)
    rec = update(
        rid, args.id,
        status=args.status,
        cv_before=args.cv_before,
        cv_after=args.cv_after,
        lb_after=args.lb_after,
        job_id=args.job_id,
        notes=args.notes,
    )
    print(json.dumps(rec, indent=2, ensure_ascii=False))
    return 0


def cmd_list(args) -> int:
    rid = _resolve(args.name)
    rows = load(rid)
    if args.proposed:
        rows = [r for r in rows if r.get("status") == "proposed"]
    rows = sorted(rows, key=priority, reverse=True)
    if not rows:
        print("（仮説はまだありません）")
        return 0
    for r in rows:
        print(
            f"{r['id']}  [{r.get('status','?'):9s}] "
            f"P={priority(r):.5f}  gain={r.get('expected_gain')} "
            f"conf={r.get('confidence')} eff={r.get('effort')}  {r.get('title','')}"
        )
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.ledger")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="add a hypothesis")
    pa.add_argument("--name", default=None)
    pa.add_argument("--title", required=True)
    pa.add_argument("--rationale", default="")
    pa.add_argument("--source", default="insight",
                    choices=["notebook", "discussion", "paper", "insight"])
    pa.add_argument("--refs", default="", help="comma-separated references")
    pa.add_argument("--expected-gain", dest="expected_gain", type=float, default=None)
    pa.add_argument("--confidence", type=float, default=None)
    pa.add_argument("--effort", default="M", choices=["S", "M", "L"])
    pa.set_defaults(func=cmd_add)

    pu = sub.add_parser("update", help="update a hypothesis by id")
    pu.add_argument("--name", default=None)
    pu.add_argument("--id", required=True)
    pu.add_argument("--status", default=None,
                    choices=["proposed", "testing", "kept", "rejected", "blocked"])
    pu.add_argument("--cv-before", dest="cv_before", type=float, default=None)
    pu.add_argument("--cv-after", dest="cv_after", type=float, default=None)
    pu.add_argument("--lb-after", dest="lb_after", type=float, default=None)
    pu.add_argument("--job-id", dest="job_id", default=None)
    pu.add_argument("--notes", default=None)
    pu.set_defaults(func=cmd_update)

    pl = sub.add_parser("list", help="list hypotheses by priority")
    pl.add_argument("--name", default=None)
    pl.add_argument("--proposed", action="store_true", help="only untested (proposed) ones")
    pl.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
