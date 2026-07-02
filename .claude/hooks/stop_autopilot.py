#!/usr/bin/env python3
"""Stop hook: optional, bounded, human-gated, GOAL-DRIVEN autopilot.

The loop's reason to keep going is a **gap to a target score**: each project
carries a ``target_score`` (the score we aim to receive at submission); after each
submit we compare the actual score to it, and if a gap remains we loop the
verification (``hypothesize -> experiment -> submit``) to close it. This hook
encodes that: it advances stages hands-off and keeps looping **while the target is
unmet and budget remains**, then finalizes.

Two hard rules always hold:
  * **Human gate** — never auto-advance out of ``scout``; a human picks the
    competition (and nothing proceeds until ``competition`` is set).
  * **Bounds** — a per-session step cap (``KLOOP_AUTOPILOT_MAX``, default 10) and a
    loop-iteration budget (``KLOOP_MAX_ITERATIONS``, default 3).

Off by default — without ``KLOOP_AUTOPILOT=1`` the agent pauses between stages.
Decision reasons are agent-facing instructions, so they stay in English.
"""

import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
CACHE = REPO / ".kloop-cache"
MAX_ADVANCES = int(os.environ.get("KLOOP_AUTOPILOT_MAX", "10"))
MAX_ITERATIONS = int(os.environ.get("KLOOP_MAX_ITERATIONS", "3"))


def _count() -> int:
    try:
        return int((CACHE / "autopilot_count").read_text().strip())
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
        name = state.current_project()
        if not name:
            _allow_stop()
        st = state.load_state(name)
    except Exception:
        _allow_stop()

    if st.get("status") == "complete":
        _allow_stop()

    stage = st.get("stage", "scout")
    status = st.get("status", "pending")
    iteration = int(st.get("iteration") or 0)

    # Small-start Kanban reminder — a started probe left un-triaged blocks the
    # experiment close, and an un-reviewed full-impl candidate blocks the
    # hypothesize close (kloop.project enforces both). Surface it so the
    # hands-off loop works the board instead of stalling on the gate.
    board_hint = ""
    try:
        from kloop import smallstart  # noqa: E402
        bits = []
        probes = smallstart.open_probes(name)
        if probes:
            bits.append(f"triage {len(probes)} started small-start probe(s) "
                        f"({', '.join(r['id'] for r in probes)}) before closing experiment")
        unrev = smallstart.unreviewed_candidates(name, iteration)
        if unrev:
            bits.append(f"review {len(unrev)} open small-start candidate(s) "
                        f"({', '.join(r['id'] for r in unrev)}) — promote/defer/drop "
                        f"(`kloop.smallstart board`) — before closing hypothesize")
        if bits:
            board_hint = " Small-start board: " + "; ".join(bits) + "."
    except Exception:
        board_hint = ""

    direction = st.get("metric_direction") or "maximize"
    target = st.get("target_score")
    actual = st.get("best_lb") if st.get("best_lb") is not None else st.get("best_cv")
    g = state.gap(target, actual, direction)
    met = state.target_met(target, actual, direction)

    # --- HUMAN GATE: never auto-advance past competition selection. -----------
    if stage == "scout" or not st.get("competition"):
        _allow_stop()

    # --- Per-session safety cap. ---------------------------------------------
    n = _count()
    if n >= MAX_ADVANCES:
        _set_count(0)
        _block(
            f"[autopilot] Reached the {MAX_ADVANCES}-step safety cap for project "
            f"{name}. Pausing. Summarize progress (target={target}, actual={actual}, "
            f"gap={g}) and ask the user whether to continue (raise KLOOP_AUTOPILOT_MAX)."
        )

    # --- Decide the next concrete action. ------------------------------------
    if status == "done":
        if stage == "survey":
            action = ("survey done — start '/kaggloop-hypothesize'. Ensure a target_score "
                      "is set (`python -m kloop.project set --target-score ...`); it is the loop's compass.")
        elif stage == "hypothesize":
            action = "hypothesize done — start '/kaggloop-experiment'"
        elif stage == "experiment":
            action = ("experiment done — start '/kaggloop-submit'. The leakage gate must pass "
                      "(`python -m kloop.gate verify`) before any submission.")
        elif stage == "submit":
            # GOAL-DRIVEN loop decision: gap to target steers it.
            if target is not None and met:
                action = (f"submit done and TARGET MET (actual={actual} reached target={target}). "
                          f"Finalize: confirm the best submission and `python -m kloop.project set --complete`.")
            elif iteration + 1 < MAX_ITERATIONS:
                action = (
                    f"submit done, target NOT met (gap={g}, actual={actual}, target={target}). "
                    f"Budget allows more ({iteration + 1}/{MAX_ITERATIONS}). STUDY THE GAP "
                    f"(`python -m kloop.project gap --log`): why are we short, what is the highest-"
                    f"leverage way to close it? Bump the iteration "
                    f"(`python -m kloop.project set --iteration {iteration + 1}`) and start a new "
                    f"round with '/kaggloop-hypothesize' targeting that gap."
                )
            else:
                action = (
                    f"submit done; loop budget ({MAX_ITERATIONS}) spent and target not reached "
                    f"(gap={g}). Finalize honestly: record best_cv/best_lb vs target in the gap "
                    f"history, write the summary, and `python -m kloop.project set --complete`."
                )
        else:
            action = f"continue working stage '{stage}'"
    else:
        action = f"continue working stage '{stage}' (status={status}) using '/kaggloop-{stage}'"

    _set_count(n + 1)
    _block(
        f"[autopilot {n + 1}/{MAX_ADVANCES}] Project {name}: {action}.{board_hint} "
        f"Keep projects/{name}/state.json, hypotheses.jsonl, progress.jsonl and README.md "
        f"current. Respect Kaggle's daily submission limit. When fully finished run "
        f"`python -m kloop.project set --complete` so autopilot stops."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
