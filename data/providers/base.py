"""Market-data provider interface (abstracted so providers are swappable).

The data layer depends on this ABC, never on a concrete vendor. To switch from
Twelve Data to (e.g.) an OANDA practice account, implement this interface and point
``data.provider`` in config at the new key — nothing downstream changes.
"""

from __future__ import annotations

import abc

import pandas as pd


class ProviderError(RuntimeError):
    """Raised on provider/transport failures or vendor-side error payloads."""


class CandleProvider(abc.ABC):
    """Fetches historical OHLCV candles and returns the canonical schema.

    Implementations MUST:
      - return the canonical candle frame (see data.candles), UTC, ascending;
      - NOT drop the forming candle themselves — the ingest layer does that, so the
        provider stays a thin transport;
      - raise ProviderError on any vendor error payload (fail-closed).
    """

    #: Map canonical timeframe keys -> provider-native interval strings.
    interval_map: dict[str, str] = {}

    name: str = "abstract"

    @abc.abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        *,
        outputsize: int = 5000,
        end: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Return up to ``outputsize`` canonical candles for ``symbol``/``timeframe``.

        If ``end`` is given, return candles at or before that instant (used to page
        backwards through history).
        """
        raise NotImplementedError

    def provider_interval(self, timeframe: str) -> str:
        try:
            return self.interval_map[timeframe]
        except KeyError as exc:
            raise ProviderError(
                f"{self.name}: timeframe '{timeframe}' not supported; "
                f"known: {sorted(self.interval_map)}"
            ) from exc
