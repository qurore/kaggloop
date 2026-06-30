#!/usr/bin/env bash
# Idempotent environment setup for kaggloop (local orchestration side).
# Builds a .venv, installs the orchestration deps + kaggle CLI, and installs uv
# so the science MCP servers can launch via .venv/bin/uvx.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "kaggloop setup — $REPO_ROOT"

# Prefer Python 3.11+, fall back to python3.
PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "✗ python3 が見つかりません。"; exit 1; }
echo "python: $($PY --version) ($PY)"

if [ ! -d ".venv" ]; then
  echo "→ .venv を作成中"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip

echo "→ 依存パッケージをインストール中"
# NOTE: pin kaggle — the current PyPI "latest" (kaggle 2.2.3 + kagglesdk 0.1.32) is a
# broken pair (ModuleNotFoundError: kagglesdk.competitions.legacy). 1.8.4 + 0.1.31 works
# and supports the new KGAT_ API access token (~/.kaggle/access_token).
python -m pip install -q \
  "kaggle==1.8.4" "kagglesdk==0.1.31" \
  numpy pandas scikit-learn \
  requests \
  uv

echo "→ 科学MCP用に uvx を確認 (.venv/bin/uvx)"
.venv/bin/uvx --version >/dev/null 2>&1 && echo "  uvx OK" || echo "  ! uvx 未検出（uv の再インストールを検討）"

# Shared Colab bridge dirs (local default; override with KLOOP_COLAB_* env).
mkdir -p .kloop-colab/queue .kloop-colab/results .kloop-cache

echo
echo "✓ セットアップ完了。次の手順:"
echo "  1) ~/.kaggle/kaggle.json を配置 (chmod 600) し、コンペのルールにWebで同意"
echo "  2) Colab ワーカーを設定 (colab/README.md)、KLOOP_COLAB_* を Drive 同期先に設定"
echo "  3) bash scripts/doctor.sh で診断"
echo "  4) Claude Code で /kaggloop または /kaggloop-scout を実行"
