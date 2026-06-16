"""Parquet candle store (local, git-ignored).

Layout: <store_dir>/<instrument_key>/<timeframe>.parquet
Each file holds the canonical candle schema. Writes are merge-on-write (idempotent):
re-ingesting overlapping ranges de-duplicates on open_time.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data.candles import CANONICAL_COLUMNS, INDEX_NAME, empty_candles, validate_candles


def candle_path(store_dir: Path, instrument_key: str, timeframe: str) -> Path:
    return Path(store_dir) / instrument_key / f"{timeframe}.parquet"


def read_candles(
    store_dir: Path, instrument_key: str, timeframe: str
) -> pd.DataFrame:
    """Read stored candles, or an empty canonical frame if none exist yet."""
    path = candle_path(store_dir, instrument_key, timeframe)
    if not path.exists():
        return empty_candles()
    df = pd.read_parquet(path)
    # Restore index/dtypes (parquet roundtrip keeps them, but be defensive).
    if df.index.name != INDEX_NAME and INDEX_NAME in df.columns:
        df = df.set_index(INDEX_NAME)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True), name=INDEX_NAME)
    df = df[CANONICAL_COLUMNS]
    return validate_candles(df.sort_index(), timeframe)


def write_candles(
    store_dir: Path,
    instrument_key: str,
    timeframe: str,
    df: pd.DataFrame,
) -> int:
    """Merge ``df`` into the store (dedupe on open_time). Returns total rows stored."""
    validate_candles(df, timeframe)
    existing = read_candles(store_dir, instrument_key, timeframe)
    combined = pd.concat([existing, df])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined = validate_candles(combined, timeframe)

    path = candle_path(store_dir, instrument_key, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, engine="pyarrow")
    return len(combined)
