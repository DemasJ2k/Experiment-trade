# AI Trading Experiment

A hands-off experiment: can an AI autonomously build, validate, and run its own trading system on a **paper/demo account** — and is the result *defensibly* profitable?

> Paper/demo only. Not financial advice. No real money. See `CLAUDE.md` for the full spec and rules.

## Status

Design locked. Building **Phase 1** (data layer + walk-forward backtest harness). See `ROADMAP.md` for the current task.

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets (config/experiment.yaml is version-controlled — the contract)
cp env_example.txt .env          # then fill in your keys (paper/demo only)
```

The exact clean-environment recipe is also recorded as the `/bootstrap-env` project
skill, and a `SessionStart` hook (`.claude/hooks/session-start.sh`) reproduces it
automatically in Claude Code on the web.

## Run Phase 1

```bash
python -m pytest                       # full suite (incl. the no-look-ahead tests)
python -m scripts.demo_walkforward     # walk-forward report on SYNTHETIC data (DoD demo)

# Real data (needs MARKET_DATA_API_KEY + FINNHUB_API_KEY in .env):
python -m data.ingest_candles          # Twelve Data: XAU/USD + US30, H1/H4/Daily
python -m data.ingest_news             # Finnhub news/sentiment + curated FOMC/CPI/NFP
```

### Phase-1 layout (built)

- `config/loader.py` — strict config loader (fail-loud) + fail-closed secret access.
- `data/` — provider-abstracted candle ingest (`providers/`), parquet store, Finnhub
  news, and the curated economic-calendar blackout source.
- `backtest/` — event-driven `engine.py` (closed candles, costs, no look-ahead),
  `walk_forward.py` (rolling IS/OOS + embargo), `metrics.py` (Sortino, WFE, Deflated
  Sharpe).
- `tests/test_no_lookahead.py` — proves the engine cannot see the forming/future bar.

## What goes where

- `CLAUDE.md` — authoritative spec, design rules, parameters, build order, guardrails.
- `ROADMAP.md` — the phased plan and the concrete next task.
- `config/experiment.yaml` — all locked parameters (account, sample, validation thresholds, safety limits).
- `data/`, `backtest/`, `strategy/`, `live/`, `safety/`, `storage/` — the build, in dependency order.

## The one rule that matters most

Phase 1 **gates** everything. No live trading loop runs until a strategy passes walk-forward validation **and** survives a multiple-testing correction. The rigor is the point of the experiment.
