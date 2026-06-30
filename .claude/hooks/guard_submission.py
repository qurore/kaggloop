#!/usr/bin/env python3
"""PreToolUse(Bash) gate: block Kaggle submissions until the leakage gate passes.

This is the enforcement teeth of the data-leakage quality gate. When the agent
tries to submit to Kaggle (``kaggle competitions submit`` or
``python -m kloop.kaggle submit``), this hook **denies** the command unless the
current project's ``gate.json`` says the leakage gate passed. That forces the
agent to actually run ``kloop.gate check`` + ``affirm`` + ``verify`` — surfacing
train/test overlap, implausible CV, single-feature leaks, group/time
contamination — before spending a submission on a possibly-leaky pipeline.

Neutral on everything else. Never hard-fails. The decision reason is agent-facing
instruction, so it stays in English.
"""

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()

# Matches a real Kaggle submission command (CLI or our wrapper).
SUBMIT_RX = re.compile(
    r"(kaggle\s+competitions\s+submit)|(kloop\.kaggle\s+submit)|(kloop/kaggle\.py\s+submit)",
    re.IGNORECASE,
)


def deny(reason: str):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command", "")
    if not command or not SUBMIT_RX.search(command):
        sys.exit(0)  # not a submission — neutral

    try:
        sys.path.insert(0, str(REPO))
        from kloop import state
        name = state.current_project()
        if not name:
            deny("[guard-submission] No active kaggloop project, but a Kaggle submission "
                 "was attempted. Create/select the project and pass the leakage gate first.")
        gp = state.gate_path(name)
        gate = json.loads(gp.read_text()) if gp.exists() else {}
    except Exception:
        # If we can't verify the gate, fail closed — a submission is outward-facing.
        deny("[guard-submission] Could not verify the leakage quality gate. Run "
             "`python -m kloop.gate check` then `affirm` then `verify` before submitting.")

    if not gate.get("passed"):
        reasons = []
        if gate.get("fails"):
            reasons.append(f"failing checks {gate['fails']}")
        if gate.get("skipped_mandatory"):
            reasons.append(f"mandatory checks not run {gate['skipped_mandatory']}")
        if gate.get("missing_affirm"):
            reasons.append(f"unaffirmed checklist {gate['missing_affirm']}")
        detail = "; ".join(reasons) or "gate.json missing or not passed"
        deny(
            f"[guard-submission] Blocked: leakage quality gate has NOT passed for project "
            f"{name} ({detail}). Run `python -m kloop.gate check ...`, fix any leaks, "
            f"`python -m kloop.gate affirm --confirm <all items>`, then "
            f"`python -m kloop.gate verify`. Do not bypass the gate — a leaky submission "
            f"wastes the daily budget and misleads the whole loop."
        )
    sys.exit(0)  # gate passed — allow


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
