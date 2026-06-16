"""The #1 silent bug: look-ahead leakage. These tests prove the engine cannot see
the forming candle or any future bar, and fills at the next bar's open — never on the
bar a decision was made on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import CostModel, Signal, run_backtest
from backtest.strategies import SmaCrossStrategy
from data.synthetic import synthetic_candles

ZERO_COST = CostModel(half_spread_price=0.0, slippage_price=0.0, commission_per_trade_usd=0.0)


class SpyStrategy:
    """Wraps a strategy and logs the history it is shown plus the signal it returns."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.name = f"spy({inner.name})"
        self.calls: list[dict] = []

    def warmup(self) -> int:
        return self.inner.warmup()

    def on_bar(self, history: pd.DataFrame):
        signal = self.inner.on_bar(history)
        self.calls.append(
            {
                "last_open_time": history.index[-1],
                "n_bars": len(history),
                "signal": None if signal is None else (signal.direction, signal.stop, signal.target),
            }
        )
        return signal


def test_history_is_a_prefix_of_closed_bars():
    """Every on_bar call sees exactly candles[:k] — no future rows, ever."""
    candles = synthetic_candles(300, seed=1)
    spy = SpyStrategy(SmaCrossStrategy(fast=5, slow=20, atr_period=10))

    seen = []

    class Recorder(SpyStrategy):
        def on_bar(self, history):
            # The history handed in must be identical to the canonical prefix.
            k = len(history)
            assert history.index.equals(candles.index[:k]), "history is not a clean prefix"
            assert history.index[-1] == candles.index[k - 1]
            seen.append(history.index[-1])
            return self.inner.on_bar(history)

    rec = Recorder(SmaCrossStrategy(fast=5, slow=20, atr_period=10))
    run_backtest(candles, rec, cost_model=ZERO_COST, timeframe="1h")
    # Decisions are made on strictly increasing closed-bar timestamps.
    assert seen == sorted(seen)
    assert max(seen) <= candles.index[-1]


def test_future_data_does_not_change_past_decisions():
    """Perturbing all bars after bar k must not change any signal emitted at/ before k."""
    base = synthetic_candles(400, seed=2)
    k = 250

    spy_a = SpyStrategy(SmaCrossStrategy(fast=10, slow=30, atr_period=14))
    run_backtest(base, spy_a, cost_model=ZERO_COST, timeframe="1h")

    # Corrupt the future: replace bars after k with extreme garbage.
    corrupted = base.copy()
    future = corrupted.index > corrupted.index[k]
    corrupted.loc[future, ["open", "high", "low", "close"]] *= 100.0

    spy_b = SpyStrategy(SmaCrossStrategy(fast=10, slow=30, atr_period=14))
    run_backtest(corrupted, spy_b, cost_model=ZERO_COST, timeframe="1h")

    cutoff = base.index[k]
    past_a = [c for c in spy_a.calls if c["last_open_time"] <= cutoff]
    past_b = [c for c in spy_b.calls if c["last_open_time"] <= cutoff]
    assert len(past_a) == len(past_b) and len(past_a) > 0
    for a, b in zip(past_a, past_b):
        assert a["last_open_time"] == b["last_open_time"]
        assert a["signal"] == b["signal"], "future data leaked into a past decision"


def test_entry_fills_at_next_bar_open_not_signal_bar():
    """A signal raised on bar t fills at bar t+1's open, never on bar t."""

    class OneShotLong:
        name = "oneshot_long"

        def __init__(self, fire_at: int):
            self.fire_at = fire_at
            self._calls = -1

        def warmup(self) -> int:
            return 1

        def on_bar(self, history: pd.DataFrame):
            self._calls = len(history) - 1  # index of current closed bar
            if self._calls == self.fire_at:
                last_close = float(history["close"].iloc[-1])
                return Signal("long", stop=last_close * 0.9, target=last_close * 1.5)
            return None

    candles = synthetic_candles(60, seed=3)
    fire_at = 30
    result = run_backtest(candles, OneShotLong(fire_at), cost_model=ZERO_COST, timeframe="1h")

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    # Entry executes at bar fire_at+1's open and timestamp — not bar fire_at.
    assert trade["entry_time"] == candles.index[fire_at + 1]
    assert trade["entry_price"] == pytest.approx(candles["open"].iloc[fire_at + 1])


def test_costs_make_entry_worse_and_exit_worse():
    """Costs must move fills against us: long buys higher, sells lower."""
    candles = synthetic_candles(60, seed=4)

    class OneShotLong:
        name = "oneshot_long"

        def warmup(self) -> int:
            return 1

        def on_bar(self, history: pd.DataFrame):
            if len(history) - 1 == 20:
                last = float(history["close"].iloc[-1])
                return Signal("long", stop=last * 0.5, target=last * 1.01)
            return None

    costed = CostModel(half_spread_price=1.0, slippage_price=0.5, commission_per_trade_usd=0.0)
    res = run_backtest(candles, OneShotLong(), cost_model=costed, timeframe="1h")
    trade = res.trades.iloc[0]
    raw_open = candles["open"].iloc[21]
    assert trade["entry_price"] == pytest.approx(raw_open + 1.5)  # paid 1.5 worse on entry


def test_no_trades_when_strategy_silent():
    candles = synthetic_candles(100, seed=5)

    class Silent:
        name = "silent"

        def warmup(self) -> int:
            return 1

        def on_bar(self, history):
            return None

    res = run_backtest(candles, Silent(), cost_model=ZERO_COST, timeframe="1h")
    assert res.n_trades == 0
    assert res.final_equity == res.starting_equity
