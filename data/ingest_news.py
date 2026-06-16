"""Ingest news (Finnhub) + persist the curated economic calendar.

Finnhub provides news + sentiment on the free tier (60 calls/min). Its economic
calendar is premium-gated, so blackout dates come from data.economic_calendar.

Stored under <store_dir>/news/ as parquet for later use (sentiment features, audit).

Usage:
    python -m data.ingest_news                       # gold + index news, last N days
    python -m data.ingest_news --symbol XAUUSD

Fail-closed: a missing FINNHUB_API_KEY raises before any network call.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from config.loader import ExperimentConfig, load_config, require_env
from data.economic_calendar import events_frame

# Finnhub category symbols for macro/general news relevant to gold + indices.
_DEFAULT_NEWS_CATEGORIES = ["general", "forex", "merger"]


def _finnhub_client():
    import finnhub

    return finnhub.Client(api_key=require_env("FINNHUB_API_KEY"))


def fetch_general_news(categories: list[str] | None = None) -> pd.DataFrame:
    """Pull Finnhub general/market news for the given categories."""
    client = _finnhub_client()
    categories = categories or _DEFAULT_NEWS_CATEGORIES
    frames: list[pd.DataFrame] = []
    for category in categories:
        items = client.general_news(category, min_id=0) or []
        if not items:
            continue
        df = pd.DataFrame(items)
        df["category"] = category
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    news = pd.concat(frames, ignore_index=True)
    if "datetime" in news.columns:
        news["timestamp"] = pd.to_datetime(news["datetime"], unit="s", utc=True)
    return news.drop_duplicates(subset=[c for c in ("id", "url") if c in news.columns])


def fetch_company_news(symbol: str, lookback_days: int) -> pd.DataFrame:
    """Pull Finnhub company/instrument news over the lookback window."""
    client = _finnhub_client()
    to_day = date.today()
    from_day = to_day - timedelta(days=lookback_days)
    items = client.company_news(
        symbol, _from=from_day.isoformat(), to=to_day.isoformat()
    ) or []
    if not items:
        return pd.DataFrame()
    df = pd.DataFrame(items)
    if "datetime" in df.columns:
        df["timestamp"] = pd.to_datetime(df["datetime"], unit="s", utc=True)
    df["symbol"] = symbol
    return df


def _write(store_dir: Path, name: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"  [news/{name}] no rows")
        return
    out = store_dir / "news"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.parquet"
    df.to_parquet(path, engine="pyarrow")
    print(f"  [news/{name}] wrote {len(df)} rows -> {path}")


def ingest_news(config: ExperimentConfig, symbols: list[str] | None = None) -> None:
    store_dir = config.store_path()

    # Always persist the curated economic calendar (no network needed).
    cal = events_frame()
    _write(store_dir, "economic_calendar", cal)
    print(f"  [calendar] {len(cal)} curated FOMC/CPI/NFP events stored")

    general = fetch_general_news()
    _write(store_dir, "general", general)

    for symbol in symbols or []:
        company = fetch_company_news(symbol, config.news.lookback_days)
        _write(store_dir, f"company_{symbol.replace('/', '')}", company)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Finnhub news + curated calendar.")
    parser.add_argument(
        "--symbol", action="append", default=[], help="company-news symbol (repeatable)"
    )
    parser.add_argument(
        "--calendar-only",
        action="store_true",
        help="store only the curated economic calendar (no Finnhub call)",
    )
    args = parser.parse_args()

    config = load_config()
    if args.calendar_only:
        cal = events_frame()
        out = config.store_path() / "news"
        out.mkdir(parents=True, exist_ok=True)
        cal.to_parquet(out / "economic_calendar.parquet", engine="pyarrow")
        print(f"Stored {len(cal)} curated events (calendar-only).")
        return
    ingest_news(config, symbols=args.symbol)


if __name__ == "__main__":
    main()
