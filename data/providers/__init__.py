"""Provider registry — resolve the configured provider, wiring secrets from .env."""

from __future__ import annotations

import os

from config.loader import ExperimentConfig, load_env, require_env
from data.providers.base import CandleProvider, ProviderError


def get_provider(config: ExperimentConfig) -> CandleProvider:
    """Instantiate the provider named in config.data.provider (secrets from .env)."""
    name = config.data.provider.lower()
    if name == "twelvedata":
        from data.providers.twelvedata import TwelveDataProvider

        api_key = require_env("MARKET_DATA_API_KEY")
        base_url = _optional_env("MARKET_DATA_BASE_URL")
        return TwelveDataProvider(api_key=api_key, base_url=base_url)
    raise ProviderError(
        f"unknown data provider '{config.data.provider}'. "
        f"Implement CandleProvider and register it in data/providers/__init__.py."
    )


def _optional_env(name: str) -> str | None:
    load_env()
    value = os.environ.get(name, "").strip()
    return value or None


__all__ = ["CandleProvider", "ProviderError", "get_provider"]
