#!/bin/bash
# SessionStart hook — make the AI Trading Experiment runnable in a fresh web container:
# venv + pinned deps + config/secrets scaffolding. Idempotent, non-interactive.
set -euo pipefail

# Web/remote sessions only; do nothing locally.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# 1. Python venv (Python 3.11+).
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

# 2. Pinned dependencies (install, not ci — leverages container caching).
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

# 3. Config + secrets scaffolding (never commits secrets; .env is git-ignored).
[ -f .env ] || cp env_example.txt .env
[ -f config/experiment.yaml ] || cp experiment.example.yaml config/experiment.yaml

# 4. Persist environment for the session so modules import from repo root and use the venv.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PYTHONPATH=\"${CLAUDE_PROJECT_DIR:-$PWD}\""
    echo "export VIRTUAL_ENV=\"${CLAUDE_PROJECT_DIR:-$PWD}/.venv\""
    echo "export PATH=\"${CLAUDE_PROJECT_DIR:-$PWD}/.venv/bin:\$PATH\""
  } >> "$CLAUDE_ENV_FILE"
fi

echo "session-start: venv ready, deps installed (RUN_MODE stays backtest; paper/demo only)."
