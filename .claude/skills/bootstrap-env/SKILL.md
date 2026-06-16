---
name: bootstrap-env
description: Reproducible clean-environment launch recipe for the AI Trading Experiment. Use at the start of ANY fresh session, container, or sub-agent before running ingest, backtest, or tests, so every run uses the same Python venv, pinned deps, and config/secrets layout. Invoke when the workspace has no .venv, when imports fail, or when setting up a new worktree.
---

# Bootstrap the AI Trading Experiment environment

Goal: get a fresh checkout to a runnable state identically every time. Paper/demo
only — never wire real-money credentials (see CLAUDE.md).

## Recipe

Run from the repo root:

```bash
# 1. Python venv (Python 3.11+)
python3 -m venv .venv
. .venv/bin/activate

# 2. Pinned dependencies
pip install --upgrade pip
pip install -r requirements.txt
# Phase 1 also needs parquet IO (not yet pinned in requirements.txt):
pip install pyarrow

# 3. Secrets + config (NOT committed)
[ -f .env ] || cp env_example.txt .env        # then fill in real keys
[ -f config/experiment.yaml ] || cp experiment.example.yaml config/experiment.yaml
```

## Invariants every run must respect

- `RUN_MODE` in `.env` is `backtest` (Phase 1) or `paper` (Phase 2) — **never `live`**.
- `.env` and `config/experiment.yaml` are git-ignored. Never commit secrets.
- Locked params live in `config/experiment.yaml`; do not hardcode them in modules.
- Closed candles only. Fail-closed on missing/stale data.
- The frozen timeframe + instrument (Phase 1) must not be re-picked later.

## Verify it worked

```bash
. .venv/bin/activate
python -c "import pandas, numpy, scipy, yaml, dotenv, finnhub, anthropic; print('deps OK')"
pytest -q   # once tests exist (e.g. tests/test_no_lookahead.py)
```

## Notes for sub-agents

Always activate the venv (`. .venv/bin/activate`) before any python/pytest call.
If the container was reclaimed, re-run the full recipe — the venv is not committed.
