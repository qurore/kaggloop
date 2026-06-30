#!/usr/bin/env python3
"""Stop hook: optional, bounded, human-gated autopilot for the win-loop.

Design intent (this is the core differentiator): **the human chooses the
competition; everything after is automated.** So this hook *never* auto-advances
out of the ``scout`` stage — it always pauses there for the human to read the
TLDR cards in ``competitions/shortlist/`` and pick. Once a competition is
selected, and only if ``KLOOP_AUTOPILOT=1``, the hook drives the inner loop
``survey -> hypothesize -> experiment -> submit`` hands-off, and loops
``hypothesize -> experiment -> submit`` for up to ``KLOOP_MAX_ITERATIONS`` full
iterations to keep improving the score.

Two independent safety bounds: a per-session auto-advance counter
(``KLOOP_AUTOPILOT_MAX``, default 10) and the loop-iteration budget
(``KLOOP_MAX_ITERATIONS``, default 3). Decision reasons are agent-facing
instructions, so they stay in English. Off by default — without the env var the
agent pauses between stages for the user to review.
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
CACHE = REPO / ".kloop-cache"
MAX_ADVANCES = int(os.environ.get("KLOOP_AUTOPILOT_MAX", "10"))
MAX_ITERATIONS = int(os.environ.get("KLOOP_MAX_ITERATIONS", "3"))
LOOP = ["hypothesize", "experiment", "submit"]


def _count() -> int:
    p = CACHE / "autopilot_count"
    try:
        return int(p.read_text().strip())
    except Exception:
        return 0


def _set_count(n: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "autopilot_count").write_text(str(n))


def _allow_stop():
    _set_count(0)
    sys.exit(0)


def _block(reason: str):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main():
    if os.environ.get("KLOOP_AUTOPILOT", "0") != "1":
        _allow_stop()

    try:
        payload = json.load(sys.stdin)
    except Exception:
        _allow_stop()

    if payload.get("stop_hook_active") and _count() >= MAX_ADVANCES:
        _allow_stop()

    try:
        sys.path.insert(0, str(REPO))
        from kloop import state
        rid = state.current_run()
        if not rid:
            _allow_stop()
        st = state.load_state(rid)
    except Exception:
        _allow_stop()

    if st.get("status") == "complete":
        _allow_stop()

    stage = st.get("stage", "scout")
    status = st.get("status", "pending")
    iteration = int(st.get("iteration") or 0)

    # --- HUMAN GATE: never auto-advance past competition selection. -----------
    if stage == "scout" or not st.get("competition"):
        _allow_stop()

    # --- Per-session safety cap. ---------------------------------------------
    n = _count()
    if n >= MAX_ADVANCES:
        _set_count(0)
        _block(
            f"[autopilot] Reached the {MAX_ADVANCES}-step safety cap for campaign "
            f"{rid}. Pausing. Summarize progress (best_cv={st.get('best_cv')}, "
            f"best_lb={st.get('best_lb')}) and ask the user whether to continue "
            f"(they can raise KLOOP_AUTOPILOT_MAX)."
        )

    # --- Decide the next concrete action. ------------------------------------
    if status == "done":
        if stage == "survey":
            action = "stage 'survey' is done — start '/kaggloop-hypothesize'"
        elif stage == "hypothesize":
            action = "stage 'hypothesize' is done — start '/kaggloop-experiment'"
        elif stage == "experiment":
            action = "stage 'experiment' is done — start '/kaggloop-submit'"
        elif stage == "submit":
            if iteration + 1 < MAX_ITERATIONS:
                action = (
                    f"submit is done (iteration {iteration}). Loop budget allows more "
                    f"({iteration + 1}/{MAX_ITERATIONS}). Bump the iteration "
                    f"(`python -m kloop.run set --iteration {iteration + 1}`), then start a "
                    f"new round with '/kaggloop-hypothesize' using what you learned "
                    f"(failed/kept hypotheses, LB feedback)."
                )
            else:
                action = (
                    f"submit is done and the loop budget ({MAX_ITERATIONS}) is spent. "
                    f"Finalize: confirm the best submission is selected, write the "
                    f"campaign summary, then `python -m kloop.run set --complete`."
                )
        else:
            action = f"continue working stage '{stage}'"
    else:
        action = f"continue working stage '{stage}' (status={status}) using '/kaggloop-{stage}'"

    _set_count(n + 1)
    _block(
        f"[autopilot {n + 1}/{MAX_ADVANCES}] Campaign {rid}: {action}. "
        f"Keep runs/{rid}/state.json, hypotheses.jsonl and campaign.md current. "
        f"Respect Kaggle's daily submission limit. When fully finished run "
        f"`python -m kloop.run set --complete` so autopilot stops."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
