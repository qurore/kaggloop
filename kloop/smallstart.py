"""Small-start Kanban — a per-project backlog of expensive-but-promising bets.

Some hypotheses are too costly to fully implement inside one loop iteration, yet
cheap to *probe*: a "small start" (1 fold, a subsample, a 2-layer stand-in, a
one-section draft) tells you whether the full build is worth it. Those bets don't
belong in the main hypothesis ledger (``hypotheses.jsonl``, which tracks bets
verified and cashed *this* loop). They belong here — a separate, Agile-Kanban
ticket board that persists and compounds across loops, so the pipeline can decide
**next** loop whether to fund the full implementation.

The board has three columns (the three Kanban stages)::

    backlog   →   verifying   →   triaged
    (added)       (probed)        (verdict: candidate | discard)

A *candidate* additionally carries a full-implementation **strength** label — the
effect prediction for the full build, which is what the next loop reads to rank
what to promote::

    very_strong | strong | moderate

Every backlog ticket is created with three MANDATORY, enforced fields (the
ticket-writing contract — the creating agent must supply them, ``add`` refuses
otherwise):
  * ``go_criteria``     — the *quantitative* full-impl Go/No-Go bar.
  * ``conditional_go``  — the fallback: conditions under which it still becomes a
    candidate even when the quantitative bar is missed.
  * ``smallstart_plan`` — a *proposed* small-start implementation (a suggestion
    the implementing agent may adapt, not obey verbatim).

Lifecycle across the loop stages (deterministically enforced in ``kloop.project``):
  * **hypothesize** — review the board: ``promote`` / ``defer`` / ``drop`` every
    open candidate (no promising candidate may be left un-reviewed this loop),
    and file new backlog tickets for expensive-but-promising ideas.
  * **experiment**  — run the cheap small-start probe for backlog tickets, then
    ``triage`` each into candidate(+strength) / discard (no probe may be left
    hanging in ``verifying`` when the stage closes).

This module is deliberately *thin* — it stores, moves, and ranks tickets; the
intelligence (which idea, what probe, what verdict) lives in the skills / you.
Record schema is one JSON object per line in ``projects/<name>/smallstart.jsonl``.
All code, comments, and console output are English.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import state

COLUMNS = ["backlog", "verifying", "triaged"]
VERDICTS = ["candidate", "discard"]
STRENGTHS = ["very_strong", "strong", "moderate"]
STRENGTH_RANK = {"very_strong": 3, "strong": 2, "moderate": 1}
STRENGTH_LABEL = {
    "very_strong": "very strong",
    "strong": "strong",
    "moderate": "moderate",
}

# The three mandatory ticket-writing fields (dest, flag, why) — enforced at add.
MANDATORY = [
    ("go_criteria", "--go-criteria",
     "the *quantitative* full-impl Go/No-Go bar "
     "(e.g. 'small-start POC shows leak-free CV >= +0.003 on >=3 folds -> Go')"),
    ("conditional_go", "--conditional-go",
     "the fallback that still makes it a candidate when the quantitative bar is "
     "missed (e.g. 'even if < +0.003, a moderate candidate when OOF corr with the "
     "current ensemble < 0.5')"),
    ("smallstart_plan", "--smallstart-plan",
     "a *proposed* small-start implementation (a suggestion the implementing agent "
     "may adapt, not obey verbatim; e.g. '1 fold + 30% subsample + a 2-layer "
     "stand-in, 20 epochs, compare OOF vs baseline on that fold')"),
]


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def board_path(run_id: str) -> Path:
    return state.project_dir(run_id) / "smallstart.jsonl"


def load(run_id: str) -> list[dict]:
    p = board_path(run_id)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _write_all(run_id: str, rows: list[dict]) -> None:
    board_path(run_id).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def _next_id(rows: list[dict]) -> str:
    n = 0
    for r in rows:
        try:
            n = max(n, int(str(r.get("id", "s0")).lstrip("s")))
        except ValueError:
            pass
    return f"s{n + 1:04d}"


def _find(rows: list[dict], tid: str) -> dict | None:
    for r in rows:
        if r.get("id") == tid:
            return r
    return None


def _current_iteration(run_id: str):
    try:
        return state.load_state(run_id).get("iteration")
    except FileNotFoundError:
        return None


# ------------------------------------------------------- enforcement query API
# (imported by kloop.project to gate stage closes — the deterministic mechanism
# that makes the board part of the loop, not a side-file.)

def open_candidates(run_id: str) -> list[dict]:
    """Triaged full-impl candidates not yet promoted or dropped — the board's live
    shortlist the next loop must act on."""
    return [r for r in load(run_id)
            if r.get("column") == "triaged"
            and r.get("verdict") == "candidate"
            and not r.get("promoted")]


def unreviewed_candidates(run_id: str, iteration) -> list[dict]:
    """Open candidates not reviewed (promote/defer/drop) in ``iteration`` — this is
    what blocks a hypothesize close: each promising candidate must be acted on
    every loop, so the board is used in the full-implementation decision."""
    return [r for r in open_candidates(run_id)
            if r.get("reviewed_iteration") != iteration]


def open_probes(run_id: str) -> list[dict]:
    """Tickets left in ``verifying`` — a started small-start probe with no verdict.
    This blocks an experiment close: never leave a probe hanging."""
    return [r for r in load(run_id) if r.get("column") == "verifying"]


def rank_key(row: dict):
    """Sort candidates strongest-first for the next loop to read."""
    return (STRENGTH_RANK.get(row.get("strength"), 0),
            row.get("reviewed_iteration") if row.get("reviewed_iteration") is not None else -1,
            row.get("iteration_verified") if row.get("iteration_verified") is not None else -1)


# --------------------------------------------------------------------- mutate

def add(run_id: str, **f) -> dict:
    rows = load(run_id)
    rec = {
        "id": _next_id(rows),
        "title": f.get("title", ""),
        "hypothesis": f.get("hypothesis", ""),
        "rationale": f.get("rationale", ""),
        "source": f.get("source", "insight"),
        "track": f.get("track") or "standard",
        "column": "backlog",
        "verdict": None,
        "strength": None,
        "iteration_added": f.get("iteration"),
        "iteration_verified": None,
        "reviewed_iteration": None,
        "promoted": False,
        "promoted_iteration": None,
        "refs": f.get("refs", []),
        # the mandatory ticket-writing contract:
        "go_criteria": f.get("go_criteria", ""),
        "conditional_go": f.get("conditional_go", ""),
        "smallstart_plan": f.get("smallstart_plan", ""),
        # probe outcome (filled at start/triage):
        "smallstart_result": None,
        "smallstart_metric": None,
        "job_id": None,
        "effort_full": f.get("effort_full", "L"),
        "notes": f.get("notes", ""),
        "created": _stamp(),
        "updated": _stamp(),
    }
    rows.append(rec)
    _write_all(run_id, rows)
    return rec


def _append_note(t: dict, note: str | None) -> None:
    if note:
        t["notes"] = (t.get("notes", "") + (" | " if t.get("notes") else "") + note)


# ------------------------------------------------------------------------- CLI

def _resolve(name: str | None) -> str:
    rid = name or state.current_project()
    if not rid:
        print("No active project (pass --name).", file=sys.stderr)
        raise SystemExit(2)
    return rid


def _get(rows: list[dict], tid: str) -> dict:
    t = _find(rows, tid)
    if t is None:
        print(f"ticket {tid!r} not found (see `kloop.smallstart board`)", file=sys.stderr)
        raise SystemExit(2)
    return t


def cmd_add(args) -> int:
    rid = _resolve(args.name)
    missing = [f"  {flag} — {desc}" for dest, flag, desc in MANDATORY
               if not (getattr(args, dest) or "").strip()]
    if missing:
        print(
            "A small-start ticket needs all three mandatory fields at creation "
            "(the contract the next loop uses to decide full implementation):\n"
            + "\n".join(missing),
            file=sys.stderr,
        )
        return 2
    refs = [r for r in (args.refs or "").split(",") if r.strip()]
    rec = add(
        rid, title=args.title, hypothesis=args.hypothesis or "", rationale=args.rationale or "",
        source=args.source, track=args.track, refs=refs,
        go_criteria=args.go_criteria, conditional_go=args.conditional_go,
        smallstart_plan=args.smallstart_plan, effort_full=args.effort_full,
        iteration=(_current_iteration(rid) if args.iteration is None else args.iteration),
    )
    print(f"Added to backlog: {rec['id']} {rec['title']}")
    print(json.dumps(rec, indent=2, ensure_ascii=False))
    return 0


def cmd_start(args) -> int:
    """backlog -> verifying: the small-start probe is being run."""
    rid = _resolve(args.name)
    rows = load(rid)
    t = _get(rows, args.id)
    if t.get("column") == "triaged":
        print("A triaged ticket cannot be (re)started; drop it and re-add if needed.",
              file=sys.stderr)
        return 2
    t["column"] = "verifying"
    if t.get("iteration_verified") is None:
        t["iteration_verified"] = _current_iteration(rid)
    if args.job_id:
        t["job_id"] = args.job_id
    _append_note(t, args.note)
    t["updated"] = _stamp()
    _write_all(rid, rows)
    print(f"Moved to verifying: {t['id']} {t['title']}  job={t.get('job_id') or '-'}")
    return 0


def cmd_triage(args) -> int:
    """verifying -> triaged: record the probe result and the verdict (+strength)."""
    rid = _resolve(args.name)
    rows = load(rid)
    t = _get(rows, args.id)
    if args.verdict == "candidate":
        if not args.strength:
            print("a 'candidate' verdict requires --strength "
                  "(very_strong|strong|moderate) — the full-impl effect prediction.",
                  file=sys.stderr)
            return 2
        if args.metric is None and not (args.result or "").strip():
            print("a 'candidate' verdict requires the probe result (--metric or "
                  "--result) — the verdict must be evidence-based.", file=sys.stderr)
            return 2
    else:  # discard
        if not (args.reason or args.result or "").strip():
            print("a 'discard' verdict requires a reason (--reason).", file=sys.stderr)
            return 2
    t["column"] = "triaged"
    t["verdict"] = args.verdict
    t["strength"] = args.strength if args.verdict == "candidate" else None
    if t.get("iteration_verified") is None:
        t["iteration_verified"] = _current_iteration(rid)
    if args.metric is not None:
        t["smallstart_metric"] = args.metric
    res = args.result or args.reason
    if res:
        t["smallstart_result"] = res
    _append_note(t, args.note)
    t["updated"] = _stamp()
    _write_all(rid, rows)
    if args.verdict == "candidate":
        print(f"Triaged {t['id']} -> full-impl candidate [{STRENGTH_LABEL.get(args.strength, '?')}] "
              f"(metric={t.get('smallstart_metric')}). Next loop's hypothesize will "
              f"promote/defer/drop it.")
    else:
        print(f"Triaged {t['id']} -> discard ({res})")
    return 0


def _review(args, mutate) -> int:
    """Shared promote/defer/drop: they all stamp reviewed_iteration (this loop
    acted on the candidate) so the hypothesize-close gate is satisfied."""
    rid = _resolve(args.name)
    rows = load(rid)
    t = _get(rows, args.id)
    if t.get("verdict") != "candidate" or t.get("column") != "triaged" or t.get("promoted"):
        print("promote/defer/drop only applies to an open full-impl candidate "
              "(triaged & candidate & not promoted).", file=sys.stderr)
        return 2
    t["reviewed_iteration"] = _current_iteration(rid)
    msg = mutate(t, args)
    _append_note(t, getattr(args, "reason", None) or getattr(args, "note", None))
    t["updated"] = _stamp()
    _write_all(rid, rows)
    print(msg)
    return 0


def cmd_promote(args) -> int:
    def m(t, a):
        t["promoted"] = True
        t["promoted_iteration"] = t["reviewed_iteration"]  # set by _review just above
        return (f"Promoted to full implementation: {t['id']} {t['title']}. "
                f"Register the full bet with `python -m kloop.ledger add` "
                f"(proposed plan: {(t.get('smallstart_plan') or '')[:60]}...).")
    return _review(args, m)


def cmd_defer(args) -> int:
    if not (args.reason or "").strip():
        print("defer requires --reason (why hold it this loop).", file=sys.stderr)
        return 2
    return _review(args, lambda t, a: f"Deferred (revisit a later loop): {t['id']} {t['title']} — {a.reason}")


def cmd_drop(args) -> int:
    if not (args.reason or "").strip():
        print("drop requires --reason.", file=sys.stderr)
        return 2

    def m(t, a):
        t["verdict"] = "discard"
        t["smallstart_result"] = (t.get("smallstart_result") or "") + f" | dropped: {a.reason}"
        return f"Dropped (off the active board): {t['id']} {t['title']} — {a.reason}"
    return _review(args, m)


def cmd_update(args) -> int:
    rid = _resolve(args.name)
    rows = load(rid)
    t = _get(rows, args.id)
    for dest in ("notes", "effort_full", "go_criteria", "conditional_go", "smallstart_plan"):
        v = getattr(args, dest)
        if v is not None:
            t[dest] = v
    if args.refs is not None:
        t["refs"] = [x for x in args.refs.split(",") if x.strip()]
    t["updated"] = _stamp()
    _write_all(rid, rows)
    print(json.dumps(t, indent=2, ensure_ascii=False))
    return 0


def _short(s, n=88) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[:n - 1] + "..."


def _track(r) -> str:
    return "[CH]" if r.get("track") == "challenge" else "    "


def cmd_board(args) -> int:
    rid = _resolve(args.name)
    rows = load(rid)
    it = _current_iteration(rid)
    print(f"=== Small-start Kanban — {rid} (iter {it}) ===")

    active = [r for r in rows if not r.get("promoted")]
    backlog = [r for r in active if r.get("column") == "backlog"]
    verifying = [r for r in active if r.get("column") == "verifying"]
    triaged = [r for r in active if r.get("column") == "triaged"]
    cands = sorted([r for r in triaged if r.get("verdict") == "candidate"],
                   key=rank_key, reverse=True)
    discards = [r for r in triaged if r.get("verdict") == "discard"]
    promoted = [r for r in rows if r.get("promoted")]

    print(f"\n[1. Backlog] {len(backlog)}")
    for r in backlog:
        print(f"  {r['id']} {_track(r)} {r.get('title', '')}  (full effort={r.get('effort_full')})")
        print(f"        go: {_short(r.get('go_criteria'))}")
    print(f"\n[2. Verifying] {len(verifying)}")
    for r in verifying:
        m = r.get("smallstart_metric")
        print(f"  {r['id']} {_track(r)} {r.get('title', '')}  job={r.get('job_id') or '-'}"
              + (f"  metric={m}" if m is not None else ""))
    print(f"\n[3. Triaged -> full-impl candidates] {len(cands)}"
          f"   <- the next loop reads these strongest-first")
    for r in cands:
        flag = "" if r.get("reviewed_iteration") == it else "  !! not reviewed this loop (promote/defer/drop)"
        print(f"  {r['id']} [{STRENGTH_LABEL.get(r.get('strength'), '?')}] {r.get('title', '')}"
              f"  metric={r.get('smallstart_metric')}{flag}")
        print(f"        go:   {_short(r.get('go_criteria'))}")
        print(f"        cond: {_short(r.get('conditional_go'))}")
    if discards:
        print(f"\n[3. Triaged -> discarded] {len(discards)}" + ("" if args.all else " (--all for details)"))
        if args.all:
            for r in discards:
                print(f"  {r['id']} {r.get('title', '')} — {_short(r.get('smallstart_result'))}")
    if promoted:
        print(f"\n[Promoted -> full implementation] {len(promoted)}")
        for r in promoted:
            print(f"  {r['id']} {r.get('title', '')} (iter {r.get('promoted_iteration')})")
    if not rows:
        print("(no tickets yet. File expensive-to-build-but-cheap-to-probe "
              "hypotheses with `python -m kloop.smallstart add ...`.)")
    return 0


def cmd_list(args) -> int:
    rid = _resolve(args.name)
    rows = load(rid)
    if args.column:
        rows = [r for r in rows if r.get("column") == args.column]
    if args.candidates:
        rows = [r for r in rows if r.get("verdict") == "candidate" and not r.get("promoted")]
    if args.iteration is not None:
        rows = [r for r in rows if r.get("iteration_added") == args.iteration]
    if not rows:
        print("(no matching tickets)")
        return 0
    for r in sorted(rows, key=rank_key, reverse=True):
        lab = STRENGTH_LABEL.get(r.get("strength"), "") if r.get("verdict") == "candidate" else ""
        tag = ("promoted" if r.get("promoted") else r.get("verdict") or r.get("column"))
        print(f"{r['id']} {_track(r)} [{tag:9s}] {('['+lab+'] ') if lab else ''}"
              f"{r.get('title', '')}  (add@it{r.get('iteration_added')})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="kloop.smallstart",
        description="Small-start Kanban: manage deferred, expensive-but-promising bets.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="add a backlog ticket (requires the 3 mandatory fields)")
    pa.add_argument("--name", default=None)
    pa.add_argument("--title", required=True)
    pa.add_argument("--hypothesis", default="", help="the bet: doing X should move the score by ~D because ...")
    pa.add_argument("--rationale", default="")
    pa.add_argument("--source", default="insight",
                    choices=["notebook", "discussion", "paper", "insight"])
    pa.add_argument("--track", default="standard", choices=["standard", "challenge"])
    pa.add_argument("--refs", default="", help="comma-separated references")
    pa.add_argument("--go-criteria", dest="go_criteria", default="",
                    help="MANDATORY: quantitative full-impl Go/No-Go bar")
    pa.add_argument("--conditional-go", dest="conditional_go", default="",
                    help="MANDATORY: fallback condition to become a candidate if the bar is missed")
    pa.add_argument("--smallstart-plan", dest="smallstart_plan", default="",
                    help="MANDATORY: proposed small-start implementation (a suggestion, not binding)")
    pa.add_argument("--effort-full", dest="effort_full", default="L", choices=["S", "M", "L"],
                    help="estimated FULL-implementation effort")
    pa.add_argument("--iteration", type=int, default=None)
    pa.set_defaults(func=cmd_add)

    pstart = sub.add_parser("start", help="move a ticket backlog -> verifying (probe running)")
    pstart.add_argument("--name", default=None)
    pstart.add_argument("--id", required=True)
    pstart.add_argument("--job-id", dest="job_id", default=None, help="colab job running the probe")
    pstart.add_argument("--note", default=None)
    pstart.set_defaults(func=cmd_start)

    pt = sub.add_parser("triage", help="move a ticket -> triaged with a verdict (candidate/discard)")
    pt.add_argument("--name", default=None)
    pt.add_argument("--id", required=True)
    pt.add_argument("--verdict", required=True, choices=VERDICTS)
    pt.add_argument("--strength", default=None, choices=STRENGTHS,
                    help="required for candidate: the full-impl effect prediction")
    pt.add_argument("--metric", type=float, default=None, help="the probed number (e.g. fold CV delta)")
    pt.add_argument("--result", default=None, help="what the probe measured (free text)")
    pt.add_argument("--reason", default=None, help="why discarded (required for discard)")
    pt.add_argument("--note", default=None)
    pt.set_defaults(func=cmd_triage)

    pp = sub.add_parser("promote", help="review a candidate -> build it now (graduates to the ledger)")
    pp.add_argument("--name", default=None)
    pp.add_argument("--id", required=True)
    pp.add_argument("--note", default=None)
    pp.set_defaults(func=cmd_promote)

    pd = sub.add_parser("defer", help="review a candidate -> keep for a later loop (--reason)")
    pd.add_argument("--name", default=None)
    pd.add_argument("--id", required=True)
    pd.add_argument("--reason", default="")
    pd.set_defaults(func=cmd_defer)

    pdr = sub.add_parser("drop", help="review a candidate -> abandon it (--reason)")
    pdr.add_argument("--name", default=None)
    pdr.add_argument("--id", required=True)
    pdr.add_argument("--reason", default="")
    pdr.set_defaults(func=cmd_drop)

    pu = sub.add_parser("update", help="edit ticket fields without moving it")
    pu.add_argument("--name", default=None)
    pu.add_argument("--id", required=True)
    pu.add_argument("--notes", default=None)
    pu.add_argument("--effort-full", dest="effort_full", default=None, choices=["S", "M", "L"])
    pu.add_argument("--refs", default=None)
    pu.add_argument("--go-criteria", dest="go_criteria", default=None)
    pu.add_argument("--conditional-go", dest="conditional_go", default=None)
    pu.add_argument("--smallstart-plan", dest="smallstart_plan", default=None)
    pu.set_defaults(func=cmd_update)

    pb = sub.add_parser("board", help="render the 3-column Kanban board")
    pb.add_argument("--name", default=None)
    pb.add_argument("--all", action="store_true", help="also list discarded tickets")
    pb.set_defaults(func=cmd_board)

    pl = sub.add_parser("list", help="flat, filterable ticket list")
    pl.add_argument("--name", default=None)
    pl.add_argument("--column", default=None, choices=COLUMNS)
    pl.add_argument("--candidates", action="store_true", help="only open full-impl candidates")
    pl.add_argument("--iteration", type=int, default=None)
    pl.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
