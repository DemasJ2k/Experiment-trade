# CLAUDE.md — AI Trading Experiment

> This file is the authoritative context for the project. Read it fully before writing code.

## What this project is

An experiment to test whether an AI can **autonomously build, validate, and run its own trading system on a PAPER/DEMO account**, and whether the result is *defensibly* profitable. It exists to settle a specific empirical question: can an AI assemble the full research → strategy → execution pipeline and produce a profitable, statistically defensible result with minimal human intervention?

**Not financial advice. Paper/demo only. No real money — ever. Never connect brokerage credentials that allow withdrawals or real-money orders.**

## The two claims being tested (keep them separate)

1. **Capability** — AI can autonomously build + run the whole pipeline. *(Expected: yes.)*
2. **Profitability** — the result is durably profitable by a pre-registered, rigorous standard. *(Open question — this is what we measure.)*

## Non-negotiable design rules

- **Fully hands-off** in live trading: every action logged, no human approval gate. Because of this, the automated **safety layer is mandatory and must operate OUTSIDE the agent** (the agent cannot disable it).
- The AI **chooses timeframe + instrument during Phase 1, then FREEZES that choice** for live trading (anti-overfitting guard).
- The strategy is **authored once, then applied** — never re-invented each cycle.
- **Closed candles only. No look-ahead, ever.**
- Always **model costs** (spread, slippage, commission).
- **Fail-closed:** missing or stale data ⇒ no trade.

## Locked parameters

- Paper account: **$50,000**. Risk per trade: **0.5–1%** ⇒ $250–$500.
- Binding-verdict sample: **100 closed live trades** (50 = interim read only).
- Reward ratio: fixed to start; the **3:1 high-confidence tier unlocks ONLY after** logged confidence is proven calibrated against outcomes.
- News / economic calendar: **Finnhub** (primary); optional Alpha Vantage news-sentiment.

## Pre-registered definition of "profitable" (the win condition)

A result counts only if **ALL** hold, measured **out-of-sample, after costs**:

- Statistically significant **positive return**
- **Beats benchmark** (buy-and-hold gold + risk-free yield)
- **Sortino > ~1**
- **≥ 100 closed trades**
- **Survives a multiple-testing correction** (Deflated Sharpe / Bonferroni)

The **2–3%/week** figure is a **LOGGED STRETCH METRIC ONLY** — never the pass/fail line.

## Build order — Phase 1 gates everything

1. Repo scaffold + config + secrets handling.
2. **Data layer:** historical candles in + stored; Finnhub news + economic calendar in.
3. **Backtest + walk-forward harness:** rolling in/out-of-sample, embargo gap, full metrics, multiple-testing correction.
4. **Strategy authoring** (AI writes ONE strategy, commits timeframe + instrument) + **graduation gate** (WFE ≥ ~0.5 AND survives correction).
   - ⛔ **GATE — nothing below runs until a strategy graduates.**
5. **Phase 2 live paper loop:** hourly, closed candles, manage-vs-scan split, position sizing.
6. **Always-on safety layer:** pre-trade gate (daily-loss breaker, drawdown breaker, position-count cap, econ-calendar blackout), kill switch, runaway/cost breaker, critic second-pass.
7. **Immutable logging** (Supabase): every prompt, response, gate decision, fill.

## Tech stack

- **Python**
- **Market data:** your data-fetching API (set in `.env`)
- **News / calendar:** Finnhub
- **Agent brain + critic pass:** Claude API
- **Storage / state / audit log:** Supabase (MCP-connectable)
- **Scheduler:** n8n or cron for the hourly trigger (n8n is MCP-connectable)

## Proposed repo structure

```
ai-trader-experiment/
├── CLAUDE.md                    # this file
├── README.md
├── ROADMAP.md                   # phased plan + the first task
├── requirements.txt
├── .env.example
├── config/
│   └── experiment.example.yaml  # all locked parameters, machine-readable
├── data/
│   ├── ingest_candles.py        # historical + ongoing market data
│   └── ingest_news.py           # Finnhub news + economic calendar
├── backtest/
│   ├── engine.py                # event-driven, closed-candles-only, costs modelled
│   ├── walk_forward.py          # rolling in/out-of-sample + embargo
│   └── metrics.py               # Sortino, max DD, profit factor, expectancy, WFE, deflated Sharpe
├── strategy/
│   ├── author.py                # Claude authors ONE strategy, commits tf + instrument
│   └── graduation_gate.py       # pass/fail vs thresholds
├── live/
│   ├── loop.py                  # hourly; manage-vs-scan
│   ├── sizing.py                # 0.5–1% risk → lot size
│   └── critic.py                # skeptical second Claude pass
├── safety/
│   ├── gates.py                 # daily-loss, drawdown, position-count, calendar blackout
│   ├── kill_switch.py           # auto-arms on threshold breach
│   └── breaker.py               # runaway/cost breaker, fail-closed
├── storage/
│   └── supabase_log.py          # immutable audit log + position state
└── tests/
    └── test_no_lookahead.py     # the #1 silent bug — test for it early
```

## Guardrails for you, Claude Code

- **Do NOT** skip walk-forward or the multiple-testing correction to reach live faster. The rigor *is* the experiment.
- **Do NOT** let the agent re-pick its timeframe after Phase 1.
- **Do NOT** connect real-money credentials — paper endpoints only.
- **Build the safety layer BEFORE** the live loop is allowed to place any order.
- Keep the strategy **simple** (few parameters); flag over-engineering.
- Write tests for the backtest engine — **look-ahead leakage is the #1 silent bug.**

## Definition of done — Phase 1

A single committed strategy **plus** a walk-forward report showing WFE, out-of-sample metrics, and multiple-testing-corrected significance, ending in a clear **graduate / no-graduate** verdict.
