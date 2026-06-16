"""Canonical candle schema + timeframe utilities.

Every provider maps its native payload onto ONE canonical OHLCV contract so the rest
of the system (store, backtest engine, walk-forward) never sees provider quirks.

Canonical candle DataFrame:
  - index:   DatetimeIndex named 'open_time', UTC tz-aware, ascending, unique.
             This is the candle's OPEN timestamp.
  - columns: open, high, low, close (float), volume (float),
             close_time (UTC tz-aware datetime).
  - INVARIANT: every stored row is a CLOSED candle (open_time + duration <= now).

Closed-candles-only is a non-negotiable design rule (no look-ahead). The helper
:func:`drop_forming_candle` enforces it at ingest time.
"""

from __future__ import annotations

import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
CANONICAL_COLUMNS = OHLCV_COLUMNS + ["close_time"]
INDEX_NAME = "open_time"

# Supported timeframes -> bar duration. Keys match config data.timeframes and the
# provider-interval mapping below.
TIMEFRAME_DURATION: dict[str, pd.Timedelta] = {
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1day": pd.Timedelta(days=1),
}


def timeframe_duration(timeframe: str) -> pd.Timedelta:
    try:
        return TIMEFRAME_DURATION[timeframe]
    except KeyError as exc:
        raise ValueError(
            f"unsupported timeframe '{timeframe}'; known: {sorted(TIMEFRAME_DURATION)}"
        ) from exc


def empty_candles() -> pd.DataFrame:
    """An empty, correctly-typed canonical candle frame."""
    df = pd.DataFrame(columns=CANONICAL_COLUMNS)
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
    df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    df.index = pd.DatetimeIndex([], name=INDEX_NAME, tz="UTC")
    return df


def make_canonical(
    open_time: pd.Series | pd.DatetimeIndex,
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    timeframe: str,
) -> pd.DataFrame:
    """Assemble a validated canonical candle frame from raw columns."""
    idx = pd.DatetimeIndex(pd.to_datetime(open_time, utc=True), name=INDEX_NAME)

    def _num(values, *, fill: float | None = None) -> "pd.Series":
        s = pd.to_numeric(pd.Series(list(values)), errors="coerce")
        return s if fill is None else s.fillna(fill)

    df = pd.DataFrame(
        {
            "open": _num(open_).to_numpy(),
            "high": _num(high).to_numpy(),
            "low": _num(low).to_numpy(),
            "close": _num(close).to_numpy(),
            "volume": _num(volume, fill=0.0).to_numpy(),
        },
        index=idx,
    )
    df["close_time"] = df.index + timeframe_duration(timeframe)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return validate_candles(df, timeframe)


def validate_candles(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Assert the canonical contract holds. Raises on violation (fail loud)."""
    if list(df.columns) != CANONICAL_COLUMNS:
        raise ValueError(
            f"candle columns {list(df.columns)} != canonical {CANONICAL_COLUMNS}"
        )
    if df.index.name != INDEX_NAME:
        raise ValueError(f"candle index must be named '{INDEX_NAME}'")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError("candle index must be a UTC tz-aware DatetimeIndex")
    if not df.index.is_monotonic_increasing:
        raise ValueError("candle index must be ascending")
    if df.index.has_duplicates:
        raise ValueError("candle index must be unique")
    if df[OHLCV_COLUMNS].isna().any().any():
        raise ValueError("candles contain NaN OHLCV values")
    duration = timeframe_duration(timeframe)
    if not (df["close_time"] == df.index + duration).all():
        raise ValueError("close_time must equal open_time + timeframe duration")
    return df


def drop_forming_candle(
    df: pd.DataFrame, timeframe: str, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Drop any candle that has not fully closed yet (closed-candles-only rule).

    A candle is closed iff close_time <= now.
    """
    if df.empty:
        return df
    if now is None:
        now = pd.Timestamp.now(tz="UTC")
    now = pd.Timestamp(now)
    if now.tz is None:
        now = now.tz_localize("UTC")
    return df[df["close_time"] <= now]
