#!/usr/bin/env python3
"""PostToolUse(Bash) hook: record a provenance line for the current campaign.

Keeps a lightweight, append-only log of shell commands run while a campaign is
active, so the pipeline is reproducible and the submit stage can audit what
actually ran (which Colab jobs, which submissions). Best-effort; never fails the
session.
"""

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    try:
        sys.path.insert(0, str(REPO))
        from kloop import state
        rid = state.current_run()
        if not rid:
            sys.exit(0)
        command = (payload.get("tool_input") or {}).get("command", "")
        rec = {
            "ts": time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime()),
            "command": command[:1000],
            "cwd": payload.get("cwd", ""),
        }
        log = state.run_dir(rid) / "experiments" / "tool_log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
