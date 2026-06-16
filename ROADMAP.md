# ROADMAP

Build in dependency order. **Phase 1 gates everything** — do not start the live loop until a strategy graduates.

## ▶ START HERE — First task: Phase 1 foundation

Build the **data layer + walk-forward backtest harness**. Do **not** build the live loop yet.

1. **Config loader** — read `config/experiment.yaml` and `.env`. Validate required keys; fail loudly if missing.
2. **`data/ingest_candles.py`** — fetch historical candles from the market-data API and store them locally (parquet/SQLite is fine). Multiple timeframes available so the strategy step can pick one. **Closed candles only.**
3. **`data/ingest_news.py`** — pull Finnhub news + the economic calendar (FOMC/CPI/NFP). Store with timestamps for blackout logic later.
4. **`backtest/engine.py`** — event-driven backtester. **Closed candles only, costs modelled** (spread/slippage/commission). No look-ahead.
5. **`backtest/walk_forward.py`** — rolling in-sample → out-of-sample windows with an **embargo gap**. Each in-sample window needs ≥100 trades or flag as noise.
6. **`backtest/metrics.py`** — Sortino, max drawdown, profit factor, expectancy, win rate, **walk-forward efficiency (WFE)**, and **Deflated Sharpe** (multiple-testing correction).
7. **`tests/test_no_lookahead.py`** — write alongside the engine. Prove the backtester cannot see the forming candle or future data. This is the #1 silent bug.

**Definition of done:** running the harness on a sample strategy produces a walk-forward report with WFE + out-of-sample metrics + corrected significance.

---

## Phase 1 (cont.) — Strategy authoring + gate

- `strategy/author.py` — Claude authors **one** strategy and commits its timeframe + instrument (then frozen).
- `strategy/graduation_gate.py` — pass only if **WFE ≥ ~0.5** AND the edge survives the multiple-testing correction. Fail → log → retry from authoring. No silent retries.

## Phase 2 — Live paper loop (only after a strategy graduates)

- `live/loop.py` — hourly, closed candles, **manage-vs-scan split** (manage open trades; scan for new only when flat).
- `live/sizing.py` — 0.5–1% risk → lot size from stop distance.
- `live/critic.py` — skeptical second Claude pass vets each trade thesis before any order.

## Phase 2 — Safety layer (build BEFORE the loop can place orders)

- `safety/gates.py` — daily-loss breaker, drawdown breaker, position-count cap, economic-calendar blackout.
- `safety/kill_switch.py` — auto-arms on threshold breach; operates outside the agent.
- `safety/breaker.py` — runaway/cost breaker (cap API calls per cycle); **fail-closed**.

## Cross-cutting — Logging

- `storage/supabase_log.py` — immutable log of every prompt, response, gate decision, and fill. This is both the confidence-calibration dataset and the evidence for the experiment's verdict.

## Reporting

- A weekly report: verdict metrics (Sortino, return vs benchmark, significance) **plus** the 2–3%/week stretch metric (logged, not pass/fail).
