"""Event-driven backtester — closed candles only, costs modelled, no look-ahead.

Core invariant (the #1 silent bug we test for):
  A signal is computed ONLY from bars up to and including the current closed bar `t`,
  and is ALWAYS executed at the OPEN of bar `t+1`. The engine never lets a strategy
  see the forming candle or any future bar, and never fills at the price of the bar
  the decision was made on.

Execution model per bar `t` (in order):
  1. Fill any pending entry (a signal raised on bar t-1's close) at bar t's OPEN,
     applying costs (half-spread + slippage to the worse side).
  2. Manage an open position against bar t's HIGH/LOW: stop / target / gap fills.
  3. If flat, ask the strategy for a signal using history[:t+1] (closed bars only);
     a returned Signal becomes the pending entry for bar t+1.

Position sizing is risk-based (0.5–1% of current equity / stop distance), per spec.
Equity is marked-to-market each bar so the curve can be resampled for Sortino/Sharpe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from config.loader import CostConfig
from data.candles import OHLCV_COLUMNS, validate_candles


# --------------------------------------------------------------------------- #
# Strategy contract
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Signal:
    """A request to OPEN a position at the next bar's open."""

    direction: str          # 'long' | 'short'
    stop: float             # absolute stop price
    target: float           # absolute take-profit price

    def __post_init__(self) -> None:
        if self.direction not in ("long", "short"):
            raise ValueError(f"direction must be long/short, got {self.direction!r}")


class Strategy(Protocol):
    name: str

    def warmup(self) -> int:
        """Bars of history required before the strategy may emit a signal."""

    def on_bar(self, history: pd.DataFrame) -> Signal | None:
        """Given closed bars up to and including the current bar, return a Signal or None.

        ``history`` is closed-candles-only; the last row is the most recent CLOSED bar.
        Consulted only when flat. The returned Signal executes at the NEXT bar's open.
        """


# --------------------------------------------------------------------------- #
# Costs / sizing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostModel:
    half_spread_price: float
    slippage_price: float
    commission_per_trade_usd: float

    @classmethod
    def from_config(cls, cost: CostConfig) -> "CostModel":
        return cls(
            half_spread_price=cost.half_spread_price,
            slippage_price=cost.slippage_price,
            commission_per_trade_usd=cost.commission_per_trade_usd,
        )

    @property
    def per_side(self) -> float:
        return self.half_spread_price + self.slippage_price

    def entry_fill(self, ref_price: float, direction: str) -> float:
        # Pay the worse side: longs buy higher, shorts sell lower.
        return ref_price + self.per_side if direction == "long" else ref_price - self.per_side

    def exit_fill(self, ref_price: float, direction: str) -> float:
        # Exit at the worse side too: longs sell lower, shorts buy higher.
        return ref_price - self.per_side if direction == "long" else ref_price + self.per_side


@dataclass(frozen=True)
class Trade:
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    units: float
    pnl_usd: float
    return_pct: float
    bars_held: int
    exit_reason: str


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series                  # mark-to-market equity per bar (index=close_time)
    starting_equity: float
    config_summary: dict = field(default_factory=dict)

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def final_equity(self) -> float:
        return float(self.equity.iloc[-1]) if len(self.equity) else self.starting_equity


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
def run_backtest(
    candles: pd.DataFrame,
    strategy: Strategy,
    *,
    cost_model: CostModel,
    timeframe: str,
    starting_equity: float = 50_000.0,
    risk_per_trade_pct: float = 0.5,
    allow_same_bar_exit: bool = True,
) -> BacktestResult:
    """Run the event-driven backtest. See module docstring for the no-look-ahead model."""
    validate_candles(candles, timeframe)
    n = len(candles)
    warmup = max(int(strategy.warmup()), 1)

    opens = candles["open"].to_numpy(dtype=float)
    highs = candles["high"].to_numpy(dtype=float)
    lows = candles["low"].to_numpy(dtype=float)
    closes = candles["close"].to_numpy(dtype=float)
    close_times = candles["close_time"].to_numpy()
    open_times = candles.index.to_numpy()

    cash = float(starting_equity)        # realized equity
    risk_frac = risk_per_trade_pct / 100.0

    pending: Signal | None = None
    pos_open = False
    pos_dir = ""
    pos_entry_price = 0.0
    pos_stop = 0.0
    pos_target = 0.0
    pos_units = 0.0
    pos_entry_idx = -1
    pos_entry_time = None

    trades: list[Trade] = []
    equity_curve = np.empty(n, dtype=float)

    def close_position(idx: int, exit_ref: float, reason: str) -> None:
        nonlocal cash, pos_open
        exit_price = cost_model.exit_fill(exit_ref, pos_dir)
        sign = 1.0 if pos_dir == "long" else -1.0
        pnl = sign * (exit_price - pos_entry_price) * pos_units
        pnl -= cost_model.commission_per_trade_usd
        cash += pnl
        ret = pnl / (cash - pnl) if (cash - pnl) > 0 else 0.0
        trades.append(
            Trade(
                direction=pos_dir,
                entry_time=pd.Timestamp(pos_entry_time),
                exit_time=pd.Timestamp(close_times[idx]),
                entry_price=pos_entry_price,
                exit_price=exit_price,
                units=pos_units,
                pnl_usd=pnl,
                return_pct=ret * 100.0,
                bars_held=idx - pos_entry_idx,
                exit_reason=reason,
            )
        )
        pos_open = False

    for t in range(n):
        # (1) Fill pending entry at THIS bar's open (signal raised on bar t-1 close).
        if pending is not None and not pos_open:
            entry_price = cost_model.entry_fill(opens[t], pending.direction)
            stop_distance = abs(entry_price - pending.stop)
            if stop_distance > 0:
                risk_amount = cash * risk_frac
                units = risk_amount / stop_distance
                pos_open = True
                pos_dir = pending.direction
                pos_entry_price = entry_price
                pos_stop = pending.stop
                pos_target = pending.target
                pos_units = units
                pos_entry_idx = t
                pos_entry_time = open_times[t]
            pending = None  # consumed (dropped if stop distance was zero)

        # (2) Manage open position against this bar's range.
        if pos_open and (allow_same_bar_exit or t > pos_entry_idx):
            hi, lo, op = highs[t], lows[t], opens[t]
            if pos_dir == "long":
                # Gap through stop at open -> fill at open (worse than stop).
                if op <= pos_stop:
                    close_position(t, op, "gap_stop")
                elif lo <= pos_stop:
                    close_position(t, pos_stop, "stop")
                elif hi >= pos_target:
                    close_position(t, pos_target, "target")
            else:  # short
                if op >= pos_stop:
                    close_position(t, op, "gap_stop")
                elif hi >= pos_stop:
                    close_position(t, pos_stop, "stop")
                elif lo <= pos_target:
                    close_position(t, pos_target, "target")

        # (3) If flat, consult strategy on CLOSED history up to and including bar t.
        if not pos_open and pending is None and t >= warmup - 1:
            history = candles.iloc[: t + 1]
            signal = strategy.on_bar(history)
            if signal is not None:
                pending = signal  # executes at bar t+1 open

        # Mark-to-market equity at this bar's close.
        if pos_open:
            sign = 1.0 if pos_dir == "long" else -1.0
            unrealized = sign * (closes[t] - pos_entry_price) * pos_units
            equity_curve[t] = cash + unrealized
        else:
            equity_curve[t] = cash

    # Close any position still open at the end of data (mark to final close).
    if pos_open and n > 0:
        last = n - 1
        close_position(last, closes[last], "end_of_data")
        equity_curve[last] = cash

    equity = pd.Series(
        equity_curve,
        index=pd.DatetimeIndex(pd.to_datetime(close_times, utc=True), name="close_time"),
        name="equity",
    )
    trades_df = _trades_to_frame(trades)
    return BacktestResult(
        trades=trades_df,
        equity=equity,
        starting_equity=starting_equity,
        config_summary={
            "timeframe": timeframe,
            "strategy": getattr(strategy, "name", strategy.__class__.__name__),
            "risk_per_trade_pct": risk_per_trade_pct,
            "cost_per_side_price": cost_model.per_side,
        },
    )


def _trades_to_frame(trades: list[Trade]) -> pd.DataFrame:
    cols = [
        "direction", "entry_time", "exit_time", "entry_price", "exit_price",
        "units", "pnl_usd", "return_pct", "bars_held", "exit_reason",
    ]
    if not trades:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame([t.__dict__ for t in trades])[cols]


__all__ = [
    "Signal",
    "Strategy",
    "CostModel",
    "Trade",
    "BacktestResult",
    "run_backtest",
    "OHLCV_COLUMNS",
]
