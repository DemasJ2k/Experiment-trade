"""Metrics: risk/return stats, WFE, and the Deflated Sharpe multiple-testing correction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import metrics as M


def _series(vals):
    idx = pd.date_range("2021-01-01", periods=len(vals), freq="1D", tz="UTC")
    return pd.Series(vals, index=idx)


def test_max_drawdown_simple():
    equity = _series([100, 120, 90, 110])
    # Peak 120 -> trough 90 = -25%.
    assert M.max_drawdown(equity) == pytest.approx(-0.25)


def test_profit_factor_and_winrate():
    trades = pd.DataFrame({"pnl_usd": [100, -50, 200, -100]})
    assert M.profit_factor(trades) == pytest.approx(300 / 150)
    assert M.win_rate(trades) == pytest.approx(0.5)
    assert M.expectancy(trades) == pytest.approx(37.5)


def test_sortino_only_penalizes_downside():
    rets = _series([0.01, -0.02, 0.015, -0.01, 0.02])
    s = M.sortino_ratio(rets)
    assert np.isfinite(s)


def test_wfe():
    assert M.walk_forward_efficiency(10.0, 5.0) == pytest.approx(0.5)
    assert np.isnan(M.walk_forward_efficiency(0.0, 5.0))


def test_expected_max_sharpe_grows_with_trials():
    v = 0.5
    assert M.expected_max_sharpe(v, 1) == 0.0
    e10 = M.expected_max_sharpe(v, 10)
    e100 = M.expected_max_sharpe(v, 100)
    assert e100 > e10 > 0.0


def test_deflated_sharpe_drops_with_more_trials():
    rng = np.random.default_rng(0)
    # A genuinely positive-mean return stream.
    rets = rng.normal(0.001, 0.01, size=1000)
    few = M.deflated_sharpe_ratio(rets, n_trials=1, sr_variance=0.0)
    many = M.deflated_sharpe_ratio(rets, n_trials=200, sr_variance=0.02)
    assert 0.0 <= many.dsr <= few.dsr <= 1.0
    # With N=1 the DSR equals PSR-vs-zero.
    assert few.dsr == pytest.approx(few.psr_vs_zero)


def test_psr_high_for_strong_track_record():
    rng = np.random.default_rng(1)
    rets = rng.normal(0.002, 0.005, size=2000)  # high Sharpe
    assert M.probabilistic_sharpe_ratio(rets, 0.0) > 0.99
