# Autonomous AI Trading Experiment — System Phases

**Purpose:** A hands-off experiment to test whether an AI (Claude API + market-data API) can autonomously build, validate, and run its own trading system on a paper/demo account — and whether the result is *defensibly* profitable.

**Core design rules**
- Fully hands-off: every action is logged; no human approval gate.
- The AI **chooses its own timeframe and instrument during Phase 1, then that choice is frozen** for live trading (anti-overfitting guard).
- The strategy is **authored once, then applied** — never re-invented each cycle.
- Closed candles only (no look-ahead). Costs (spread/slippage) are always modelled.

---

## Phase 0 — Pre-registration (lock before anything runs)

Both parties sign off on the win condition *before* any data is touched. The result only counts if it meets **all** of:

- Statistically significant **positive return**
- Measured **out-of-sample** (not the data the strategy was built on)
- **After** spreads, commissions, and slippage
- **Beats a benchmark** (buy-and-hold gold + risk-free yield)
- **Risk-adjusted:** Sortino ratio above ~1
- Over a sample of **100 closed trades**
- Survives a **multiple-testing correction** (Deflated Sharpe / Bonferroni)

Profitability is defined by **edge**, not by a return target. The **2–3%/week** figure is kept only as a **secondary stretch metric** — logged and reported, but *not* the pass/fail line. (Sustained 2–3%/week compounds to ~180–365% a year, beyond any real track record, so using it as the bar would make the test unwinnable.)

This is what makes the verdict binding and removes "it was just luck" as an out.

---

## Phase 1 — Strategy creation (gated)

1. **Author.** AI ingests historical data, writes *one* strategy, and commits its timeframe + instrument(s).
2. **Walk-forward validation.** Rolling in-sample → unseen out-of-sample windows, with an **embargo gap** between them to prevent data leakage. Each window needs **100+ trades (ideally 200+)** or the result is treated as noise.
3. **Graduation gate.** The strategy advances to live-paper **only if**:
   - Walk-forward efficiency clears a threshold (≈ 0.5 or higher), **and**
   - The edge survives the multiple-testing correction.
4. **Fail handling.** Fails the gate → returns to step 1, logged. No silent retries.

---

## Phase 2 — Live paper-trading loop (hands-off, hourly)

- **Trigger:** hourly, on **closed candles only**.
- **Manage-vs-scan split:**
  - *Manage* open trades — exit only on structural invalidation; no idle fiddling.
  - *Scan* for a new entry **only when flat**.
- **Position sizing:** risk **0.5–1% of equity** per trade. Stop distance (from structure / ATR) determines the lot size.
- **Reward ratio:** starts at a fixed ratio. The **3:1 "high-confidence" tier unlocks only after** logged confidence is proven calibrated against actual outcomes.
- **Application:** the frozen Phase-1 strategy is *applied*, not rewritten.

---

## Always-On Safety Layer (operates outside the agent)

Because the system is fully hands-off, these automated controls are the only thing that can stop a bad loop.

- **Pre-trade gate:** daily-loss circuit breaker · drawdown circuit breaker · position-count cap · economic-calendar blackout (no entries into FOMC / CPI / NFP).
- **Kill switch:** auto-arms when loss thresholds are breached.
- **Runaway / cost breaker:** caps API calls per cycle; **fail-closed** — no fresh data means no trade.
- **Critic second-pass:** a skeptical second AI call vets the trade thesis before any order is placed.
- **Immutable log:** every prompt, response, gate decision, and fill is recorded — this is both the calibration dataset and the evidence for the debate.

---

## Locked Parameters

| Item | Value | Note |
|---|---|---|
| Paper account balance | **$50,000** | At 0.5–1% risk = **$250–$500 per trade** |
| Sample size | **100 closed live trades** | The binding verdict gate (50 would be an interim read only) |
| News / economic-calendar feed | **Finnhub** (primary) | Bundles news, sentiment, and the economic calendar in one feed; optional add: Alpha Vantage news-sentiment (official MCP server) |
| Profitability definition | **Agreed** | Beats benchmark · after costs · Sortino > ~1 · statistically significant |
| Win condition sign-off | **Agreed by both parties** | Phase 0 locked |

---

*This document defines the experiment architecture only. It is not financial advice; the system runs on a paper/demo account.*
