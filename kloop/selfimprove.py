"""Results-driven pipeline self-improvement — mechanics only (results-ism).

At the tail of EVERY loop iteration (the end of ``/kaggloop-submit``) the agent
asks: *did this round actually improve the realized score?* Only when the answer
is yes does it analyze what worked and — if a generalizable process lesson
exists — edit the pipeline itself (``.claude/skills/**``, ``.claude/hooks/**``,
``CLAUDE.md``). This module is the thin mechanical support for that flow; the
intelligence (the retrospective, the lesson, the edit) stays in the skill:

    python -m kloop.selfimprove check      # did the realized score improve vs prior loops?
    python -m kloop.selfimprove log ...    # append the outcome to .claude/self-improvements.jsonl
    python -m kloop.selfimprove list       # read the history (never re-apply a reverted idea)
    python -m kloop.selfimprove hookcheck  # syntax + smoke-run every hook (run after editing one)

The trigger is a *realized* score delta computed from ``progress.jsonl`` — never
a hunch. The self-improvement log is append-only, like ``decisions.jsonl`` (the
exec guard protects both). All console output, code, and comments are English.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import state

# Outcome vocabulary for `log --action` (one entry per loop iteration, always).
LOG_ACTIONS = ["improved_and_changed", "improved_no_change", "no_improvement", "reverted"]

DEFAULT_SIG_FRAC = float(os.environ.get("KLOOP_SELFIMPROVE_SIG_FRAC", "0.10"))


def _resolve(name):
    n = name or state.current_project()
    if not n:
        print("No active project (pass --name).", file=sys.stderr)
        raise SystemExit(2)
    return n


def _log_path() -> Path:
    return state.REPO / ".claude" / "self-improvements.jsonl"


def _read_progress(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("actual") is not None:
                rows.append(rec)
    return rows


# ------------------------------------------------------------------------ check

def cmd_check(args) -> int:
    """Direction-aware: is this iteration's realized score better than the best
    of all PREVIOUS iterations? Compares within progress.jsonl (appended by
    `kloop.project gap --log`), so it only ever sees real recorded scores."""
    if args.file:
        ppath = Path(args.file)
        name = args.name or state.current_project()
        st = {}
        if name:
            try:
                st = state.load_state(name)
            except FileNotFoundError:
                pass
    else:
        name = _resolve(args.name)
        st = state.load_state(name)
        ppath = state.progress_path(name)

    direction = args.direction or st.get("metric_direction") or "maximize"
    target = args.target if args.target is not None else st.get("target_score")
    rows = _read_progress(ppath)
    if target is None and rows:
        target = rows[-1].get("target")

    out = {"project": name, "direction": direction, "target": target,
           "sig_frac": args.sig_frac, "iteration": None, "current": None,
           "prev_best": None, "delta": None, "improved": None,
           "first_score": False, "prev_gap": None, "gap_closed_frac": None,
           "significant": False}

    if not rows:
        out["first_score"] = True
        print(json.dumps(out, indent=2, ensure_ascii=False))
        print("No progress history yet (run this after `kloop.project gap --log`). "
              "Do not self-improve; only record.", file=sys.stderr)
        return 0

    best = max if direction == "maximize" else min
    cur_iter = rows[-1].get("iteration")
    cur_rows = [r for r in rows if r.get("iteration") == cur_iter]
    prev_rows = [r for r in rows if r.get("iteration") != cur_iter]
    current = best(float(r["actual"]) for r in cur_rows)
    out["iteration"], out["current"] = cur_iter, current

    if not prev_rows:
        out["first_score"] = True
        print(json.dumps(out, indent=2, ensure_ascii=False))
        print("First score (no baseline to compare). Normally do not self-improve; just `log` it.", file=sys.stderr)
        return 0

    prev_best = best(float(r["actual"]) for r in prev_rows)
    delta = (current - prev_best) if direction == "maximize" else (prev_best - current)
    improved = delta > 0
    prev_gap = state.gap(target, prev_best, direction)
    gap_closed_frac = None
    if improved and prev_gap is not None and prev_gap > 0:
        gap_closed_frac = round(delta / prev_gap, 4)
    if not improved:
        significant = False
    elif prev_gap is None or prev_gap <= 0:
        # No target to scale by, or already past it — any real gain is notable.
        significant = True
    else:
        significant = gap_closed_frac >= args.sig_frac

    out.update({"prev_best": prev_best, "delta": round(delta, 6), "improved": improved,
                "prev_gap": prev_gap, "gap_closed_frac": gap_closed_frac,
                "significant": significant})
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if improved and significant:
        print(f"Large improvement (delta={delta:+.6g}"
              + (f", closed {gap_closed_frac:.0%} of the remaining gap" if gap_closed_frac is not None else "")
              + "). Analyze what worked; if a generalizable lesson exists, self-improve "
                "skills/hooks/CLAUDE.md (always record via selfimprove log + journal).", file=sys.stderr)
    elif improved:
        print(f"Improvement (small, delta={delta:+.6g}). Self-improve only if the lesson is clear. "
              "Either way, record it via log.", file=sys.stderr)
    else:
        print(f"No improvement (delta={delta:+.6g}). Do not change the pipeline at all "
              "(`log --action no_improvement`). If the previous loop self-improved, "
              "consider reverting that change as a regression suspect.", file=sys.stderr)
    return 0


# -------------------------------------------------------------------- log / list

def cmd_log(args) -> int:
    name = args.name or state.current_project()
    iteration = args.iteration
    if iteration is None and name:
        try:
            iteration = state.load_state(name).get("iteration")
        except FileNotFoundError:
            pass
    rec = {
        "ts": state._stamp(),
        "project": name,
        "iteration": iteration,
        "action": args.action,
        "analysis": args.analysis,
        "files": [f.strip() for f in (args.files or "").split(",") if f.strip()],
        "rationale": args.rationale or "",
        "delta": args.delta,
        "gap_closed_frac": args.gap_closed_frac,
    }
    path = Path(args.file) if args.file else _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"self-improvement logged: [{name}#{iteration}] {args.action}: {args.analysis}")
    return 0


def cmd_list(args) -> int:
    path = Path(args.file) if args.file else _log_path()
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    rows = rows[-args.n:] if args.n else rows
    if not rows:
        print("(no self-improvement log yet)")
        return 0
    for r in rows:
        extra = []
        if r.get("delta") is not None:
            extra.append(f"Δ={r['delta']}")
        if r.get("gap_closed_frac") is not None:
            extra.append(f"gap_closed_frac={r['gap_closed_frac']}")
        print(f"{r.get('ts')}  [{r.get('project')}#{r.get('iteration')}] "
              f"{r.get('action')}" + (("  " + " ".join(extra)) if extra else ""))
        if r.get("analysis"):
            print(f"    analysis: {r['analysis']}")
        if r.get("files"):
            print(f"    changed: {', '.join(r['files'])}")
        if r.get("rationale"):
            print(f"    └ {r['rationale']}")
    return 0


# -------------------------------------------------------------------- hookcheck

def cmd_hookcheck(args) -> int:
    """Syntax-check + smoke-run every hook. A self-improvement edit that breaks a
    hook is worse than no improvement — run this after ANY hook edit. The smoke
    run feeds an empty ``{}`` payload with CLAUDE_PROJECT_DIR pointed at a temp
    dir, so no real project/cache state is touched."""
    import py_compile

    hooks_dir = state.REPO / ".claude" / "hooks"
    files = sorted(hooks_dir.glob("*.py"))
    if not files:
        print("(no .py hooks in .claude/hooks/)")
        return 0
    failures = 0
    with tempfile.TemporaryDirectory(prefix="kloop-hookcheck-") as tmp:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = tmp
        env["KLOOP_AUTOPILOT"] = "0"
        for f in files:
            problem = None
            try:
                py_compile.compile(str(f), cfile=os.path.join(tmp, f.name + "c"), doraise=True)
            except py_compile.PyCompileError as e:
                problem = f"syntax error: {str(e).splitlines()[0]}"
            if problem is None:
                try:
                    p = subprocess.run(
                        [sys.executable, str(f)], input="{}", text=True,
                        capture_output=True, timeout=args.timeout, env=env, cwd=tmp)
                    if p.returncode != 0:
                        problem = (f"smoke-run exit={p.returncode}: "
                                   f"{(p.stderr or p.stdout).strip()[:200]}")
                except subprocess.TimeoutExpired:
                    problem = f"smoke-run timeout (>{args.timeout}s)"
            if problem:
                failures += 1
                print(f"  ✗ {f.name} — {problem}")
            else:
                print(f"  ✓ {f.name}")
    if failures:
        print(f"{failures} hook(s) are broken — restore the previous content immediately "
              "(restoring takes priority over self-improvement).", file=sys.stderr)
        return 2
    print("all hooks OK (syntax + smoke-run)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kloop.selfimprove")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="did this iteration improve the realized score? (the trigger)")
    pc.add_argument("--name", default=None)
    pc.add_argument("--sig-frac", dest="sig_frac", type=float, default=DEFAULT_SIG_FRAC,
                    help="fraction of the remaining gap that counts as 'significant' (default 0.10)")
    pc.add_argument("--direction", choices=["maximize", "minimize"], default=None,
                    help="override metric direction (defaults to project state)")
    pc.add_argument("--target", type=float, default=None,
                    help="override target score (defaults to project state)")
    pc.add_argument("--file", default=None,
                    help="progress.jsonl path override (testing)")
    pc.set_defaults(func=cmd_check)

    pl = sub.add_parser("log", help="append this loop's self-improvement outcome (append-only)")
    pl.add_argument("--name", default=None)
    pl.add_argument("--action", required=True, choices=LOG_ACTIONS)
    pl.add_argument("--analysis", required=True,
                    help="one-line what-worked / why-skipped analysis")
    pl.add_argument("--files", default="",
                    help="comma-separated pipeline files changed (empty when none)")
    pl.add_argument("--rationale", default="", help="why the lesson generalizes (or why not)")
    pl.add_argument("--delta", type=float, default=None, help="realized score delta from `check`")
    pl.add_argument("--gap-closed-frac", dest="gap_closed_frac", type=float, default=None)
    pl.add_argument("--iteration", type=int, default=None)
    pl.add_argument("--file", default=None, help="log path override (testing)")
    pl.set_defaults(func=cmd_log)

    pls = sub.add_parser("list", help="read the self-improvement history")
    pls.add_argument("--n", type=int, default=10, help="show only the last N entries (0 = all)")
    pls.add_argument("--file", default=None, help="log path override (testing)")
    pls.set_defaults(func=cmd_list)

    ph = sub.add_parser("hookcheck", help="syntax + smoke-run every hook (run after editing one)")
    ph.add_argument("--timeout", type=float, default=30.0)
    ph.set_defaults(func=cmd_hookcheck)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
