"""Shared campaign-state / run-directory helpers for the kaggloop skills.

A *campaign* is one Kaggle competition we are trying to win. Everything about a
campaign lives in a single self-contained directory under ``runs/<id>/`` and
``state.json`` is the source of truth that drives the skills, the SessionStart
banner, and the (opt-in) autopilot Stop hook.

These helpers are deliberately thin: the intelligence lives in the skills (i.e.
in you, the Claude Code agent). This module only does the mechanical bookkeeping
so a campaign is reproducible and resumable across sessions.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "runs"
CACHE = REPO / ".kloop-cache"

# The win-loop stages, in order. The loop body (hypothesize -> experiment ->
# submit) repeats; "scout" is a one-time, human-gated entry point.
STAGES = ["scout", "survey", "hypothesize", "experiment", "submit"]
# Stages that form the repeating inner loop the autopilot may cycle through.
LOOP_STAGES = ["hypothesize", "experiment", "submit"]


def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return (text or "campaign")[:60]


def run_dir(run_id: str) -> Path:
    return RUNS / run_id


def state_path(run_id: str) -> Path:
    return run_dir(run_id) / "state.json"


def load_state(run_id: str) -> dict:
    p = state_path(run_id)
    if not p.exists():
        raise FileNotFoundError(f"no state.json for run {run_id!r} ({p})")
    return json.loads(p.read_text())


def save_state(run_id: str, state: dict) -> None:
    state["updated"] = _stamp()
    state_path(run_id).write_text(json.dumps(state, indent=2))


def set_current(run_id: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "current_run").write_text(run_id)


def current_run() -> str | None:
    p = CACHE / "current_run"
    if p.exists():
        rid = p.read_text().strip()
        if rid and run_dir(rid).exists():
            return rid
    return None


def new_run(slug: str, competition: str = "", metric: str = "") -> str:
    """Create a campaign directory and its initial state.

    ``competition`` is the Kaggle competition slug (empty until scout/human pick
    one); ``metric`` is the evaluation metric name once known.
    """
    slug = slugify(slug)
    run_id = f"{_stamp()}_{slug}"
    d = run_dir(run_id)
    for sub in (
        "experiments/code",
        "experiments/jobs",
        "experiments/results",
        "experiments/plots",
        "submissions",
    ):
        (d / sub).mkdir(parents=True, exist_ok=True)
    # An empty hypothesis ledger so downstream helpers can always append.
    (d / "hypotheses.jsonl").touch()
    state = {
        "run_id": run_id,
        "slug": slug,
        "competition": competition,   # kaggle competition slug
        "metric": metric,             # evaluation metric name
        "metric_direction": "",       # "maximize" | "minimize" (set during survey)
        "stage": "scout",
        "status": "pending",          # pending | running | done | complete
        "iteration": 0,               # how many full hypothesize->submit loops done
        "best_cv": None,              # best local cross-validation score so far
        "best_lb": None,              # best public leaderboard score so far
        "best_submission": None,      # path to the submission that scored best_lb
        "created": _stamp(),
        "updated": _stamp(),
    }
    save_state(run_id, state)
    (d / "campaign.md").write_text(
        f"# Campaign: {slug}\n\n"
        f"- **Run id:** {run_id}\n"
        f"- **Competition:** {competition or '(not selected yet)'}\n"
        f"- **Metric:** {metric or '(unknown)'}\n\n"
        f"## Log\n\n- {_stamp()} — campaign created (stage: scout)\n"
    )
    set_current(run_id)
    return run_id


def append_campaign_log(run_id: str, line: str) -> None:
    p = run_dir(run_id) / "campaign.md"
    with p.open("a") as f:
        f.write(f"- {_stamp()} — {line}\n")
