"""Ingest historical candles for the frozen instrument universe.

Fetches deep history per (instrument, timeframe) by paging backwards, enforces the
closed-candles-only rule (drops the forming bar), and merges into the parquet store.

Usage:
    python -m data.ingest_candles                 # all instruments, all timeframes
    python -m data.ingest_candles --instrument xauusd --timeframe 1h

Fail-closed: a missing MARKET_DATA_API_KEY raises before any work begins.
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from config.loader import ExperimentConfig, load_config
from data.candles import drop_forming_candle, timeframe_duration
from data.providers import CandleProvider, ProviderError, get_provider
from data.store import read_candles, write_candles


def ingest_one(
    config: ExperimentConfig,
    provider: CandleProvider,
    instrument_key: str,
    timeframe: str,
    *,
    now: pd.Timestamp | None = None,
    pause_s: float = 8.0,
) -> int:
    """Page history backwards for one (instrument, timeframe); store closed candles."""
    instrument = config.instrument(instrument_key)
    symbol = instrument.provider_symbol
    store_dir = config.store_path()
    duration = timeframe_duration(timeframe)
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)

    end: pd.Timestamp | None = None
    earliest_seen: pd.Timestamp | None = None
    total = 0
    for batch in range(config.data.max_history_batches):
        try:
            df = provider.fetch_candles(symbol, timeframe, outputsize=5000, end=end)
        except ProviderError as exc:
            if batch == 0:
                raise  # nothing fetched at all -> fail loud
            print(f"  [{instrument_key}/{timeframe}] stopping early: {exc}")
            break

        df = drop_forming_candle(df, timeframe, now=now)
        if df.empty:
            break

        total = write_candles(store_dir, instrument_key, timeframe, df)
        batch_earliest = df.index.min()
        print(
            f"  [{instrument_key}/{timeframe}] batch {batch + 1}: "
            f"+{len(df)} rows, range {df.index.min()} .. {df.index.max()}"
        )

        # Stop if this page didn't extend history further back.
        if earliest_seen is not None and batch_earliest >= earliest_seen:
            break
        earliest_seen = batch_earliest

        # Next page ends one bar before the earliest bar we have.
        end = batch_earliest - duration
        if batch < config.data.max_history_batches - 1:
            time.sleep(pause_s)  # respect free-tier rate limit (8 credits/min)

    stored = read_candles(store_dir, instrument_key, timeframe)
    print(
        f"  [{instrument_key}/{timeframe}] stored total: {len(stored)} rows "
        f"({stored.index.min()} .. {stored.index.max()})"
        if len(stored)
        else f"  [{instrument_key}/{timeframe}] stored total: 0 rows"
    )
    return total


def ingest_all(
    config: ExperimentConfig,
    *,
    instruments: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> None:
    provider = get_provider(config)
    instruments = instruments or sorted(config.instruments)
    timeframes = timeframes or list(config.data.timeframes)
    print(f"Provider: {provider.name} | instruments: {instruments} | tfs: {timeframes}")
    for instrument_key in instruments:
        for timeframe in timeframes:
            ingest_one(config, provider, instrument_key, timeframe)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest historical candles.")
    parser.add_argument("--instrument", help="instrument key (default: all)")
    parser.add_argument("--timeframe", help="timeframe (default: all configured)")
    args = parser.parse_args()

    config = load_config()
    ingest_all(
        config,
        instruments=[args.instrument] if args.instrument else None,
        timeframes=[args.timeframe] if args.timeframe else None,
    )


if __name__ == "__main__":
    main()
