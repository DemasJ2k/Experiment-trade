"""Config loader: strict validation, fail-loud on bad/missing keys, secret guards."""

from __future__ import annotations

import pytest

from config.loader import (
    ConfigError,
    get_run_mode,
    load_config,
    require_env,
)


def test_loads_and_types():
    cfg = load_config()
    assert cfg.account.paper_balance_usd == 50_000
    assert 0.5 <= cfg.account.risk_per_trade_pct <= 1.0
    assert set(cfg.instruments) == {"xauusd", "us30"}
    assert "1day" in cfg.data.timeframes
    # Every instrument has a cost model (we always model costs).
    for key in cfg.instruments:
        assert cfg.cost(key).half_spread_price >= 0


def test_unknown_instrument_raises():
    cfg = load_config()
    with pytest.raises(ConfigError):
        cfg.instrument("eurusd")


def test_missing_secret_fails_closed():
    # .env ships blank, so a required secret must raise rather than silently proceed.
    with pytest.raises(ConfigError):
        require_env("MARKET_DATA_API_KEY")


def test_run_mode_rejects_live(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "live")
    with pytest.raises(ConfigError):
        get_run_mode()


def test_run_mode_default_backtest(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "backtest")
    assert get_run_mode() == "backtest"


def test_bad_risk_pct_rejected(tmp_path):
    import yaml

    cfg = load_config()
    raw = dict(cfg.raw)
    raw["account"] = {"paper_balance_usd": 50000, "risk_per_trade_pct": 5.0}
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError):
        load_config(p)
