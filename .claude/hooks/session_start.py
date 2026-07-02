#!/usr/bin/env python3
"""SessionStart hook: print a short kaggloop environment + campaign status banner.

Whatever this prints on stdout is added to the session context, so it doubles as
orientation for the agent: is the env ready, is a competition campaign in
progress, what to do next. Must never crash the session — everything is
best-effort. All console output is English.
"""

import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def _read_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _has(cmd):
    return shutil.which(cmd) is not None


def _venv_has(name):
    return (REPO / ".venv" / "bin" / name).exists()


def main():
    _read_stdin()  # consume payload; we don't need its fields
    lines = ["=== kaggloop on Claude Code — environment ==="]

    venv = REPO / ".venv"
    lines.append(f"venv:        {'ready' if venv.exists() else 'missing (run scripts/setup.sh)'}")

    kaggle_ok = _venv_has("kaggle") or _has("kaggle")
    creds = ((Path.home() / ".kaggle" / "access_token").exists()
             or (Path.home() / ".kaggle" / "kaggle.json").exists()
             or bool(os.environ.get("KAGGLE_KEY")) or bool(os.environ.get("KAGGLE_API_TOKEN")))
    lines.append(f"kaggle CLI:  {'yes' if kaggle_ok else 'no (pip install kaggle)'}"
                 f" / auth: {'configured' if creds else 'not set (~/.kaggle/access_token)'}")

    uvx = _venv_has("uvx") or _has("uvx")
    lines.append(f"science MCP: {'uvx present (arxiv / semantic-scholar)' if uvx else 'uvx missing (setup.sh)'}")

    queue = os.environ.get("KLOOP_COLAB_QUEUE")
    lines.append(f"Colab:       {'queue=' + queue if queue else 'default (.kloop-colab/, Drive sync recommended)'}")

    # Current project, if any.
    try:
        sys.path.insert(0, str(REPO))
        from kloop import smallstart, state  # noqa: E402
        name = state.current_project()
        if name:
            st = state.load_state(name)
            comp = st.get("competition") or "(no competition selected)"
            direction = st.get("metric_direction") or "maximize"
            actual = st.get("best_lb") if st.get("best_lb") is not None else st.get("best_cv")
            g = state.gap(st.get("target_score"), actual, direction)
            gate = "PASS" if st.get("gate_passed") else "not passed"
            ndec = len(state.load_decisions(name))
            subs_cap = st.get("max_daily_submissions")
            lines.append(
                f"current project: {name}\n"
                f"  comp={comp}  stage={st.get('stage')}  status={st.get('status')}  iter={st.get('iteration')}"
                f"  subs/day={subs_cap if subs_cap is not None else '-'}\n"
                f"  best_cv={st.get('best_cv')}  best_lb={st.get('best_lb')}  "
                f"target={st.get('target_score')}  gap={('%.4g' % g) if g is not None else '-'}\n"
                f"  leakage gate={gate}  decisions logged={ndec} (kloop.journal show)"
            )
            # Small-start Kanban summary — only when the board is in use.
            board = smallstart.load(name)
            if board:
                bl = sum(1 for r in board if r.get("column") == "backlog")
                vf = sum(1 for r in board if r.get("column") == "verifying")
                cands = smallstart.open_candidates(name)
                unrev = smallstart.unreviewed_candidates(name, st.get("iteration"))
                by = {s: sum(1 for r in cands if r.get("strength") == s)
                      for s in ("very_strong", "strong", "moderate")}
                warn = f"  !! {len(unrev)} unreviewed" if unrev else ""
                lines.append(
                    f"  small-start: backlog {bl} / verifying {vf} / candidates {len(cands)}"
                    f" (very_strong {by['very_strong']} / strong {by['strong']} / moderate {by['moderate']})"
                    f"{warn} (kloop.smallstart board)"
                )
        else:
            lines.append("current project: none — start with `/kaggloop` or `/kaggloop-scout`")
    except Exception:
        pass

    autopilot = os.environ.get("KLOOP_AUTOPILOT", "0") == "1"
    lines.append(f"autopilot:   {'ON (auto stage advance)' if autopilot else 'off (confirm each stage)'}")
    lines.append("Skills: /kaggloop, /kaggloop-scout, -survey, -hypothesize, -experiment, -submit")

    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
