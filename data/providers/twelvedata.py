"""Twelve Data REST provider (https://api.twelvedata.com).

Endpoint: GET /time_series
  params: symbol, interval, outputsize (<=5000), order, timezone, apikey,
          optional end_date to page backwards through history.
Response: {"meta": {...}, "values": [{datetime, open, high, low, close, volume}, ...],
           "status": "ok"}  OR  {"code": 4xx, "message": "...", "status": "error"}

Free tier: 8 API credits/min, 800/day; /time_series costs 1 credit per symbol.

Docs: https://twelvedata.com/docs#time-series ,
      https://support.twelvedata.com/en/articles/5615854-credits
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from data.candles import make_canonical
from data.providers.base import CandleProvider, ProviderError

_DEFAULT_BASE_URL = "https://api.twelvedata.com"


class TwelveDataProvider(CandleProvider):
    name = "twelvedata"

    # Canonical timeframe -> Twelve Data interval string.
    interval_map = {
        "1h": "1h",
        "4h": "4h",
        "1day": "1day",
    }

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        if not api_key:
            raise ProviderError("TwelveDataProvider requires a non-empty api_key")
        self.api_key = api_key
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        outputsize: int = 5000,
        end: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        interval = self.provider_interval(timeframe)
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": min(int(outputsize), 5000),
            "order": "ASC",
            "timezone": "UTC",
            "apikey": self.api_key,
        }
        if end is not None:
            end = pd.Timestamp(end)
            if end.tz is not None:
                end = end.tz_convert("UTC").tz_localize(None)
            params["end_date"] = end.strftime("%Y-%m-%d %H:%M:%S")

        payload = self._get("/time_series", params)
        return self._to_canonical(payload, timeframe, symbol)

    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:  # transport failure
                last_err = exc
            else:
                # 429 = rate limited; back off and retry.
                if resp.status_code == 429:
                    last_err = ProviderError("twelvedata: 429 rate limited")
                else:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise ProviderError(
                            f"twelvedata: non-JSON response (HTTP {resp.status_code})"
                        ) from exc
                    # Vendor error payloads carry status=='error' or a 'code'.
                    if isinstance(data, dict) and data.get("status") == "error":
                        raise ProviderError(
                            f"twelvedata error {data.get('code')}: {data.get('message')}"
                        )
                    if resp.status_code != 200:
                        raise ProviderError(
                            f"twelvedata: HTTP {resp.status_code}: {data}"
                        )
                    return data
            time.sleep(2 ** attempt)  # exponential backoff: 1,2,4,8s
        raise ProviderError(
            f"twelvedata: request failed after {self.max_retries} retries: {last_err}"
        )

    @staticmethod
    def _to_canonical(payload: dict, timeframe: str, symbol: str) -> pd.DataFrame:
        values = payload.get("values") if isinstance(payload, dict) else None
        if not values:
            raise ProviderError(
                f"twelvedata: empty 'values' for {symbol}/{timeframe}: {payload}"
            )
        raw = pd.DataFrame(values)
        required = {"datetime", "open", "high", "low", "close"}
        missing = required - set(raw.columns)
        if missing:
            raise ProviderError(f"twelvedata: response missing columns {missing}")
        if "volume" not in raw.columns:
            raw["volume"] = 0.0
        return make_canonical(
            open_time=raw["datetime"],
            open_=raw["open"],
            high=raw["high"],
            low=raw["low"],
            close=raw["close"],
            volume=raw["volume"],
            timeframe=timeframe,
        )


def build_provider(api_key: str, base_url: str | None = None) -> TwelveDataProvider:
    return TwelveDataProvider(api_key=api_key, base_url=base_url)
