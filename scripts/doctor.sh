#!/usr/bin/env bash
# Diagnose the kaggloop environment. Read-only; exits 0.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }

echo "kaggloop — doctor"
echo "repo: $REPO_ROOT"

echo "[core]"
command -v claude >/dev/null 2>&1 && ok "claude CLI: $(claude --version 2>/dev/null)" || warn "claude CLI not found (skills/hooks run inside Claude Code)"
[ -d ".venv" ] && ok ".venv present: $(.venv/bin/python --version 2>&1)" || bad ".venv missing — run scripts/setup.sh"

echo "[python deps]"
if [ -d ".venv" ]; then
  for mod in numpy pandas sklearn requests; do
    .venv/bin/python -c "import $mod" 2>/dev/null && ok "import $mod" || bad "import $mod (run setup.sh)"
  done
  .venv/bin/python -c "import kloop.state, kloop.project, kloop.ledger, kloop.colab, kloop.score, kloop.gate, kloop.journal" 2>/dev/null \
    && ok "kloop package imports" || bad "kloop package import failed"
fi

echo "[kaggle]"
if [ -x ".venv/bin/kaggle" ] || command -v kaggle >/dev/null 2>&1; then
  ok "kaggle CLI present"
else
  bad "kaggle CLI missing (pip install kaggle / setup.sh)"
fi
if [ -f "$HOME/.kaggle/kaggle.json" ]; then
  ok "kaggle.json present"
  perms="$(stat -f '%A' "$HOME/.kaggle/kaggle.json" 2>/dev/null || stat -c '%a' "$HOME/.kaggle/kaggle.json" 2>/dev/null)"
  [ "$perms" = "600" ] && ok "kaggle.json perms 600" || warn "kaggle.json perms $perms (chmod 600 recommended)"
elif [ -n "${KAGGLE_KEY:-}" ]; then
  ok "KAGGLE_USERNAME/KAGGLE_KEY set in env"
else
  warn "no Kaggle credentials (~/.kaggle/kaggle.json or KAGGLE_* env) — needed to download/submit"
fi

echo "[science MCP]"
if [ -x ".venv/bin/uvx" ]; then
  ok "uvx present (arxiv / semantic-scholar launch via .venv/bin/uvx)"
else
  warn "uvx missing — run setup.sh (MCP literature search won't start)"
fi
echo "    (in Claude Code, run /mcp to confirm the servers are connected)"

echo "[colab bridge]"
Q="${KLOOP_COLAB_QUEUE:-$REPO_ROOT/.kloop-colab/queue}"
R="${KLOOP_COLAB_RESULTS:-$REPO_ROOT/.kloop-colab/results}"
[ -d "$Q" ] && ok "queue dir: $Q" || warn "queue dir not found: $Q (set KLOOP_COLAB_QUEUE to your Drive-synced folder)"
[ -d "$R" ] && ok "results dir: $R" || warn "results dir not found: $R (set KLOOP_COLAB_RESULTS)"
[ "${KLOOP_COLAB_QUEUE:-}" = "" ] && warn "KLOOP_COLAB_QUEUE unset — using local default (no Colab sync). See colab/README.md"

echo "[projects]"
if [ -d ".venv" ]; then
  .venv/bin/python -m kloop.project list 2>/dev/null || echo "  (none yet)"
fi
