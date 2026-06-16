"""Walk-forward harness: window geometry, embargo gap, and end-to-end report shape."""

from __future__ import annotations

import numpy as np

from backtest.strategies import sma_cross_factory
from backtest.walk_forward import generate_windows, run_walk_forward
from config.loader import load_config
from data.synthetic import synthetic_candles


def test_window_geometry_and_embargo():
    windows = generate_windows(
        n_bars=3000,
        in_sample_bars=1500,
        out_of_sample_bars=500,
        step_bars=500,
        embargo_bars=30,
        anchored=False,
    )
    assert len(windows) >= 2
    for is0, is1, oos0, oos1 in windows:
        # Embargo gap actually separates IS end from OOS start (purge).
        assert oos0 == is1 + 30
        assert oos1 - oos0 == 500
        assert is1 - is0 == 1500
        assert oos1 <= 3000


def test_no_windows_when_too_short():
    assert generate_windows(
        n_bars=100, in_sample_bars=1500, out_of_sample_bars=500,
        step_bars=500, embargo_bars=30, anchored=False,
    ) == []


def test_report_end_to_end_shape():
    cfg = load_config()
    candles = synthetic_candles(3200, timeframe="1day", seed=21)
    grid = [
        {"fast": 10, "slow": 30, "atr_mult": 2.0, "reward": 2.0},
        {"fast": 8, "slow": 24, "atr_mult": 1.5, "reward": 2.0},
    ]
    report = run_walk_forward(
        candles, sma_cross_factory, grid,
        config=cfg, timeframe="1day", instrument_key="xauusd",
    )
    assert report.n_param_trials == 2
    assert len(report.windows) >= 1
    assert "dsr" in report.deflated_sharpe
    assert "oos_n_trades" in report.aggregate
    # WFE and DSR are computed (may be nan on edgeless synthetic data, but present).
    assert isinstance(report.mean_wfe, float)
    for w in report.windows:
        assert w.oos_start > w.is_end  # OOS strictly after IS (embargo enforced)
