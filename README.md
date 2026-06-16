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

# 3. Configure secrets and parameters
cp .env.example .env                              # then fill in your keys
cp config/experiment.example.yaml config/experiment.yaml
```

## What goes where

- `CLAUDE.md` — authoritative spec, design rules, parameters, build order, guardrails.
- `ROADMAP.md` — the phased plan and the concrete next task.
- `config/experiment.yaml` — all locked parameters (account, sample, validation thresholds, safety limits).
- `data/`, `backtest/`, `strategy/`, `live/`, `safety/`, `storage/` — the build, in dependency order.

## The one rule that matters most

Phase 1 **gates** everything. No live trading loop runs until a strategy passes walk-forward validation **and** survives a multiple-testing correction. The rigor is the point of the experiment.
