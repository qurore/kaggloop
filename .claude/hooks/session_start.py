#!/usr/bin/env python3
"""SessionStart hook: print a short kaggloop environment + campaign status banner.

Whatever this prints on stdout is added to the session context, so it doubles as
orientation for the agent: is the env ready, is a competition campaign in
progress, what to do next. Must never crash the session — everything is
best-effort. Console output is Japanese.
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
    lines = ["=== kaggloop on Claude Code — 環境 ==="]

    venv = REPO / ".venv"
    lines.append(f"venv:        {'準備OK' if venv.exists() else '未作成（scripts/setup.sh を実行）'}")

    kaggle_ok = _venv_has("kaggle") or _has("kaggle")
    creds = (Path.home() / ".kaggle" / "kaggle.json").exists() or bool(os.environ.get("KAGGLE_KEY"))
    lines.append(f"kaggle CLI:  {'あり' if kaggle_ok else '無し（pip install kaggle）'}"
                 f" / 認証: {'設定済み' if creds else '未設定（~/.kaggle/kaggle.json）'}")

    uvx = _venv_has("uvx") or _has("uvx")
    lines.append(f"科学MCP:     {'uvx あり（arxiv / semantic-scholar）' if uvx else 'uvx 無し（setup.sh）'}")

    queue = os.environ.get("KLOOP_COLAB_QUEUE")
    lines.append(f"Colab連携:   {'キュー=' + queue if queue else '既定（.kloop-colab/、Drive同期を推奨）'}")

    # Current project, if any.
    try:
        sys.path.insert(0, str(REPO))
        from kloop import state  # noqa: E402
        name = state.current_project()
        if name:
            st = state.load_state(name)
            comp = st.get("competition") or "（コンペ未選択）"
            direction = st.get("metric_direction") or "maximize"
            actual = st.get("best_lb") if st.get("best_lb") is not None else st.get("best_cv")
            g = state.gap(st.get("target_score"), actual, direction)
            gate = "✓合格" if st.get("gate_passed") else "未通過"
            ndec = len(state.load_decisions(name))
            lines.append(
                f"現在のプロジェクト: {name}\n"
                f"  コンペ={comp}  stage={st.get('stage')}  status={st.get('status')}  iter={st.get('iteration')}\n"
                f"  best_cv={st.get('best_cv')}  best_lb={st.get('best_lb')}  "
                f"target={st.get('target_score')}  gap={('%.4g' % g) if g is not None else '-'}\n"
                f"  リークゲート={gate}  意思決定ログ={ndec}件（kloop.journal show で確認）"
            )
        else:
            lines.append("現在のプロジェクト: なし — `/kaggloop` または `/kaggloop-scout` で開始")
    except Exception:
        pass

    autopilot = os.environ.get("KLOOP_AUTOPILOT", "0") == "1"
    lines.append(f"autopilot:   {'ON（stage自動進行）' if autopilot else 'off（stage毎に確認）'}")
    lines.append("Skills: /kaggloop, /kaggloop-scout, -survey, -hypothesize, -experiment, -submit")

    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
