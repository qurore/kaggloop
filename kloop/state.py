"""Shared project-state / workspace helpers for the kaggloop skills.

A *project* is one Kaggle competition we are trying to win. Everything about a
project — its state, dossier, hypotheses, **all** implementation and verification
code, experiment results, submissions, and notes — lives in one self-contained
folder under ``projects/<name>/``. ``state.json`` is the source of truth that
drives the skills, the SessionStart banner, the leakage quality gate, and the
(opt-in) autopilot Stop hook.

The win-loop is **goal-driven**: each project carries a ``target_score`` (the
score we aim to receive at submission). Every iteration compares the *actual*
score against that target, studies the **gap**, and loops the verification to
close it. ``progress.jsonl`` records that target-vs-actual history.

These helpers are deliberately thin: the intelligence lives in the skills (you,
the Claude Code agent). They do the mechanical bookkeeping so a project is
reproducible and resumable.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECTS = REPO / "projects"
CACHE = REPO / ".kloop-cache"

# The win-loop stages, in order. The loop body (hypothesize -> experiment ->
# submit) repeats until the target is met; "scout" is a one-time, human-gated
# entry point.
STAGES = ["scout", "survey", "hypothesize", "experiment", "submit"]
LOOP_STAGES = ["hypothesize", "experiment", "submit"]


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return (text or "project")[:60]


def project_dir(name: str) -> Path:
    return PROJECTS / name


def state_path(name: str) -> Path:
    return project_dir(name) / "state.json"


def progress_path(name: str) -> Path:
    return project_dir(name) / "progress.jsonl"


def gate_path(name: str) -> Path:
    return project_dir(name) / "gate.json"


def load_state(name: str) -> dict:
    p = state_path(name)
    if not p.exists():
        raise FileNotFoundError(f"no state.json for project {name!r} ({p})")
    return json.loads(p.read_text())


def save_state(name: str, state: dict) -> None:
    state["updated"] = _stamp()
    state_path(name).write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _session_id() -> str | None:
    """A per-session id so parallel kaggloop sessions don't share one 'current
    project' pointer (which lets one session's commands land on another's
    project). Prefer an explicit id; fall back to the POSIX session id (stable
    per controlling terminal). Returns None if none is derivable."""
    sid = os.environ.get("KLOOP_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", sid.strip())[:64]
    try:
        return f"sid{os.getsid(0)}"
    except (OSError, AttributeError):
        return None


def _read_pointer(p: Path) -> str | None:
    if p.exists():
        name = p.read_text().strip()
        if name and project_dir(name).exists():
            return name
    return None


def set_current(name: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    sid = _session_id()
    if sid:
        # Per-session pointer only — never touch the shared legacy pointer, so we
        # can't clobber another concurrent session's 'current project'.
        (CACHE / f"current_project__{sid}").write_text(name)
    else:
        (CACHE / "current_project").write_text(name)


def current_project() -> str | None:
    # Resolution precedence (most explicit first) so concurrent sessions don't
    # collide on one shared pointer:
    #   1) KLOOP_PROJECT env override (per-shell/session, deterministic)
    #   2) this session's own pointer file
    #   3) the legacy global pointer (back-compat)
    env = (os.environ.get("KLOOP_PROJECT") or "").strip()
    if env and project_dir(env).exists():
        return env
    sid = _session_id()
    for p in ([CACHE / f"current_project__{sid}"] if sid else []) + [CACHE / "current_project"]:
        name = _read_pointer(p)
        if name:
            return name
    return None


def _unique_name(slug: str) -> str:
    base = slugify(slug)
    name = base
    n = 2
    while project_dir(name).exists():
        name = f"{base}-{n}"
        n += 1
    return name


def new_project(slug: str, competition: str = "", metric: str = "") -> str:
    """Create a self-contained project workspace and its initial state."""
    name = _unique_name(slug)
    d = project_dir(name)
    # Optimized, self-contained layout: ALL project files live here.
    for sub in (
        "code",                    # all implementation + verification code
        "experiments/jobs",        # submitted Colab job specs
        "experiments/results",     # results ingested back from Colab
        "experiments/plots",       # figures
        "submissions",             # submission CSVs + leaderboard.jsonl
        "notebooks",               # synced top-Public-Score notebooks + manifest.json
        "notes",                   # free-form MD: analyses, decisions, scratch
        "data",                    # local data scratch (also gitignored)
    ):
        (d / sub).mkdir(parents=True, exist_ok=True)
    (d / "hypotheses.jsonl").touch()
    (d / "smallstart.jsonl").touch()   # small-start Kanban board (see kloop.smallstart)
    state = {
        "name": name,
        "slug": slugify(slug),
        "competition": competition,    # kaggle competition slug
        "metric": metric,              # evaluation metric name
        "metric_direction": "",        # "maximize" | "minimize" (set during survey)
        "scoring_mode": "",            # "automated" | "judged" | "hybrid" (set during survey)
        "target_score": None,          # the score we AIM to receive at submission
        "target_rationale": "",        # why that target (LB percentiles, medal line, ...)
        "stage": "scout",
        "status": "pending",           # pending | running | done | complete
        "iteration": 0,                # how many full hypothesize->submit loops done
        "best_cv": None,               # best local cross-validation score so far
        "best_lb": None,               # best public leaderboard score so far
        "best_submission": None,       # path to the submission that scored best_lb
        "gate_passed": False,          # leakage quality gate cleared for the latest sub
        "created": _stamp(),
        "updated": _stamp(),
    }
    save_state(name, state)
    (d / "README.md").write_text(
        f"# Project: {name}\n\n"
        f"- **Competition:** {competition or '(not selected yet)'}\n"
        f"- **Metric:** {metric or '(unknown)'}\n"
        f"- **Target score:** (set during survey)\n\n"
        f"This folder is self-contained — all code, experiments, submissions, and notes\n"
        f"for this project live here. See `../README.md` for the projects layout and the\n"
        f"gitignore toggle.\n\n"
        f"## Log\n\n- {_stamp()} — project created (stage: scout)\n"
    )
    set_current(name)
    return name


def append_project_log(name: str, line: str) -> None:
    p = project_dir(name) / "README.md"
    with p.open("a") as f:
        f.write(f"- {_stamp()} — {line}\n")


# --------------------------------------------------------------------------- gap

def gap(target, actual, direction: str):
    """Signed gap to the target (positive = target not yet reached).

    maximize: gap = target - actual   (need actual to rise)
    minimize: gap = actual - target   (need actual to fall)
    Returns None if target or actual is missing.
    """
    if target is None or actual is None:
        return None
    target, actual = float(target), float(actual)
    return (target - actual) if direction == "maximize" else (actual - target)


def target_met(target, actual, direction: str) -> bool:
    g = gap(target, actual, direction)
    return g is not None and g <= 0


def append_progress(name: str, rec: dict) -> None:
    rec = {"ts": _stamp(), **rec}
    with progress_path(name).open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ------------------------------------------------------------- decision journal

def journal_path(name: str) -> Path:
    return project_dir(name) / "decisions.jsonl"


def append_decision(name: str, rec: dict) -> dict:
    """Append one decision to the append-only project journal (observability).

    The journal is the audit trail a human reads later to reconstruct *why* the
    current model exists. It is append-only by construction here, and the
    PreToolUse guard blocks shell that would rewrite or delete it.
    """
    rec = {"ts": _stamp(), **rec}
    with journal_path(name).open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load_decisions(name: str) -> list[dict]:
    p = journal_path(name)
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


def decisions_for(name: str, stage: str, iteration) -> list[dict]:
    return [d for d in load_decisions(name)
            if d.get("stage") == stage and d.get("iteration") == iteration]
