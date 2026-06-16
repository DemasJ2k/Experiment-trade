"""Sample strategies for exercising the harness.

These are NOT the graduating Phase-1 strategy (that is authored once in
strategy/author.py and frozen). They exist only to validate the backtest engine,
walk-forward harness, and metrics end-to-end, per the ROADMAP definition of done.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Signal


def _atr(history: pd.DataFrame, period: int) -> float:
    high = history["high"].to_numpy(dtype=float)
    low = history["low"].to_numpy(dtype=float)
    close = history["close"].to_numpy(dtype=float)
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
    return float(np.mean(tr[-period:]))


class SmaCrossStrategy:
    """Long/short on fast/slow SMA crossover; ATR-based stop and R-multiple target."""

    def __init__(
        self,
        fast: int = 20,
        slow: int = 50,
        atr_period: int = 14,
        atr_mult: float = 2.0,
        reward: float = 2.0,
    ) -> None:
        if fast >= slow:
            raise ValueError("fast period must be < slow period")
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.reward = reward
        self.name = f"sma_cross(f={fast},s={slow},atr={atr_mult}x,R={reward})"

    def warmup(self) -> int:
        return self.slow + 1 + self.atr_period

    def on_bar(self, history: pd.DataFrame) -> Signal | None:
        close = history["close"]
        if len(close) < self.warmup():
            return None
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        f_now, f_prev = fast_ma.iloc[-1], fast_ma.iloc[-2]
        s_now, s_prev = slow_ma.iloc[-1], slow_ma.iloc[-2]
        if np.isnan([f_now, f_prev, s_now, s_prev]).any():
            return None

        atr = _atr(history, self.atr_period)
        if atr <= 0:
            return None
        last_close = float(close.iloc[-1])
        risk = self.atr_mult * atr

        # Bullish crossover -> long.
        if f_prev <= s_prev and f_now > s_now:
            return Signal("long", stop=last_close - risk, target=last_close + self.reward * risk)
        # Bearish crossover -> short.
        if f_prev >= s_prev and f_now < s_now:
            return Signal("short", stop=last_close + risk, target=last_close - self.reward * risk)
        return None


def sma_cross_factory(params: dict) -> SmaCrossStrategy:
    return SmaCrossStrategy(**params)
