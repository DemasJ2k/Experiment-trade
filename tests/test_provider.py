"""Twelve Data provider: canonical mapping + fail-closed on vendor error payloads.

Uses a fake session, so no network or API key is required.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data.candles import CANONICAL_COLUMNS
from data.providers.base import ProviderError
from data.providers.twelvedata import TwelveDataProvider


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status
        self.last_params = None

    def get(self, url, params=None, timeout=None):
        self.last_params = params
        return _FakeResp(self._payload, self._status)


_OK_PAYLOAD = {
    "meta": {"symbol": "XAU/USD", "interval": "1h"},
    "status": "ok",
    "values": [
        {"datetime": "2024-01-01 00:00:00", "open": "2000", "high": "2010",
         "low": "1995", "close": "2005", "volume": "100"},
        {"datetime": "2024-01-01 01:00:00", "open": "2005", "high": "2015",
         "low": "2000", "close": "2012", "volume": "120"},
    ],
}


def test_parses_to_canonical():
    session = _FakeSession(_OK_PAYLOAD)
    provider = TwelveDataProvider(api_key="x", session=session)
    df = provider.fetch_candles("XAU/USD", "1h")
    assert list(df.columns) == CANONICAL_COLUMNS
    assert df.index.tz is not None and str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing
    # close_time = open_time + 1h.
    assert (df["close_time"] - df.index == pd.Timedelta(hours=1)).all()
    # Request was shaped correctly (ascending, UTC, interval mapped).
    assert session.last_params["order"] == "ASC"
    assert session.last_params["timezone"] == "UTC"
    assert session.last_params["interval"] == "1h"


def test_vendor_error_payload_fails_closed():
    payload = {"code": 401, "message": "Invalid API key", "status": "error"}
    provider = TwelveDataProvider(api_key="x", session=_FakeSession(payload))
    with pytest.raises(ProviderError):
        provider.fetch_candles("XAU/USD", "1h")


def test_unsupported_timeframe_raises():
    provider = TwelveDataProvider(api_key="x", session=_FakeSession(_OK_PAYLOAD))
    with pytest.raises(ProviderError):
        provider.fetch_candles("XAU/USD", "5min")
