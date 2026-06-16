"""Curated economic-calendar blackout source (FOMC / CPI / NFP).

Finnhub's economic-calendar endpoint is premium-gated on the free tier, so we curate
these publicly-scheduled, high-impact US events ourselves:

  - FOMC : rate decision, 14:00 ET on the second meeting day (exact dates published
           by the Fed ~a year ahead).
  - CPI  : BLS release, 08:30 ET (curated monthly dates — REFRESH from bls.gov yearly).
  - NFP  : BLS Employment Situation, 08:30 ET, first Friday of the month (computed).

Event times are built as ET wall-clock then converted to UTC via zoneinfo, so DST is
handled correctly. The blackout window (hours before/after) comes from config.

NOTE: curated dates must be refreshed annually. This module is the Phase-2 blackout
input; in Phase 1 we ingest/store it so it is ready when the live loop is built.
Sources: federalreserve.gov/monetarypolicy/fomccalendars.htm , bls.gov/schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config.loader import ExperimentConfig

_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")

# FOMC rate-decision dates (second/announcement day). Publicly scheduled.
_FOMC_DATES = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (Fed published schedule)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

# CPI release dates (08:30 ET). Curated — REFRESH yearly from bls.gov/schedule.
_CPI_DATES = [
    # 2025
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
    "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-15",
    "2025-11-13", "2025-12-10",
    # 2026 (approximate BLS schedule — verify)
    "2026-01-13", "2026-02-11", "2026-03-11", "2026-04-10", "2026-05-12",
    "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11", "2026-10-13",
    "2026-11-13", "2026-12-10",
]


@dataclass(frozen=True)
class EconomicEvent:
    name: str          # 'FOMC' | 'CPI' | 'NFP'
    timestamp: pd.Timestamp  # UTC tz-aware
    description: str


def _et_to_utc(date_str: str, hour: int, minute: int) -> pd.Timestamp:
    y, m, d = (int(x) for x in date_str.split("-"))
    et = datetime(y, m, d, hour, minute, tzinfo=_ET)
    return pd.Timestamp(et.astimezone(_UTC))


def _nfp_dates(start_year: int, end_year: int) -> list[str]:
    """First Friday of each month in [start_year, end_year]."""
    out: list[str] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            d = datetime(year, month, 1)
            # weekday(): Mon=0 .. Fri=4
            offset = (4 - d.weekday()) % 7
            first_friday = d + timedelta(days=offset)
            out.append(first_friday.strftime("%Y-%m-%d"))
    return out


def all_events(start_year: int = 2025, end_year: int = 2026) -> list[EconomicEvent]:
    """Return the curated event list across the year range, sorted by time."""
    events: list[EconomicEvent] = []
    for d in _FOMC_DATES:
        events.append(EconomicEvent("FOMC", _et_to_utc(d, 14, 0), "FOMC rate decision"))
    for d in _CPI_DATES:
        events.append(EconomicEvent("CPI", _et_to_utc(d, 8, 30), "US CPI release"))
    for d in _nfp_dates(start_year, end_year):
        events.append(EconomicEvent("NFP", _et_to_utc(d, 8, 30), "US Nonfarm Payrolls"))
    return sorted(events, key=lambda e: e.timestamp)


def events_frame(start_year: int = 2025, end_year: int = 2026) -> pd.DataFrame:
    """Curated events as a DataFrame (for storage / inspection)."""
    events = all_events(start_year, end_year)
    return pd.DataFrame(
        {
            "timestamp": [e.timestamp for e in events],
            "name": [e.name for e in events],
            "description": [e.description for e in events],
        }
    )


def in_blackout(
    ts: pd.Timestamp,
    config: ExperimentConfig,
    *,
    events: list[EconomicEvent] | None = None,
) -> tuple[bool, EconomicEvent | None]:
    """Is ``ts`` inside the blackout window of a configured high-impact event?

    Window = [event - blackout_hours_before, event + blackout_hours_after].
    Only events listed in config.safety.calendar_blackout_events count.
    """
    ts = pd.Timestamp(ts)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    watched = set(config.safety.calendar_blackout_events)
    before = pd.Timedelta(hours=config.economic_calendar.blackout_hours_before)
    after = pd.Timedelta(hours=config.economic_calendar.blackout_hours_after)
    for event in events if events is not None else all_events():
        if event.name not in watched:
            continue
        if event.timestamp - before <= ts <= event.timestamp + after:
            return True, event
    return False, None
