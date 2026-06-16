"""Synthetic candle generator for tests and harness demos.

Generates a canonical OHLCV frame from a geometric-random-walk close series. Used to
exercise the engine/harness without network access or API keys. NOT market data — it
carries no real edge; it only validates plumbing and the no-look-ahead property.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.candles import make_canonical, timeframe_duration


def synthetic_candles(
    n: int,
    *,
    timeframe: str = "1h",
    start: str = "2020-01-01",
    seed: int = 7,
    start_price: float = 2000.0,
    drift: float = 0.00002,
    vol: float = 0.004,
) -> pd.DataFrame:
    """Return ``n`` canonical candles driven by a seeded geometric random walk."""
    rng = np.random.default_rng(seed)
    step = timeframe_duration(timeframe)
    open_times = pd.date_range(start=start, periods=n, freq=step, tz="UTC")

    rets = rng.normal(drift, vol, size=n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    # Intrabar w"iggle proportional to vol; high/low envelope the open/close.
    wiggle = np.abs(rng.normal(0, vol, size=n)) * close
    high = np.maximum(open_, close) + wiggle
    low = np.minimum(open_, close) - wiggle
    volume = rng.integers(100, 1000, size=n).astype(float)

    return make_canonical(open_times, open_, high, low, close, volume, timeframe)
