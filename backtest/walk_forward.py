"""Walk-forward harness: rolling in-sample -> out-of-sample with an embargo gap.

For each window:
  1. Run every parameter set in the grid on the IN-SAMPLE slice.
  2. Select the best IS config (Sharpe), subject to the in-sample minimum-trade gate
     (windows that can't meet it are flagged as noise).
  3. Evaluate ONLY the selected config on the OUT-OF-SAMPLE slice, which begins after
     an EMBARGO gap (purge) to prevent leakage across the IS/OOS boundary.

Aggregate OOS returns are stitched across windows and passed through the Deflated
Sharpe Ratio, with the number of trials set to the breadth of the parameter search —
this is the multiple-testing correction the experiment requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from backtest import metrics as M
from backtest.engine import CostModel, Strategy, run_backtest
from config.loader import ExperimentConfig
from data.candles import timeframe_duration

StrategyFactory = Callable[[dict], Strategy]


@dataclass
class WindowResult:
    index: int
    is_start: pd.Timestamp
    is_end: pd.Timestamp
    oos_start: pd.Timestamp
    oos_end: pd.Timestamp
    chosen_params: dict
    is_metrics: dict
    oos_metrics: dict
    wfe: float
    oos_returns: pd.Series
    oos_trades: pd.DataFrame
    is_trade_gate_met: bool


@dataclass
class WalkForwardReport:
    timeframe: str
    instrument: str
    windows: list[WindowResult] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    deflated_sharpe: dict = field(default_factory=dict)
    mean_wfe: float = float("nan")
    n_param_trials: int = 0


def _embargo_bars(config: ExperimentConfig, timeframe: str) -> int:
    """Convert embargo_days to whole bars of the given timeframe (>=1)."""
    bar = timeframe_duration(timeframe)
    days = pd.Timedelta(days=config.validation.embargo_days)
    return max(1, int(np.ceil(days / bar)))


def generate_windows(
    n_bars: int,
    *,
    in_sample_bars: int,
    out_of_sample_bars: int,
    step_bars: int,
    embargo_bars: int,
    anchored: bool,
) -> list[tuple[int, int, int, int]]:
    """Yield (is_start, is_end, oos_start, oos_end) bar indices (end-exclusive)."""
    windows: list[tuple[int, int, int, int]] = []
    is_start = 0
    while True:
        is_end = is_start + in_sample_bars
        oos_start = is_end + embargo_bars
        oos_end = oos_start + out_of_sample_bars
        if oos_end > n_bars:
            break
        windows.append((is_start, is_end, oos_start, oos_end))
        is_start = 0 if anchored else is_start + step_bars
        if anchored:
            # Anchored: IS always starts at 0 but grows; advance the IS end instead.
            in_sample_bars += step_bars
    return windows


def run_walk_forward(
    candles: pd.DataFrame,
    factory: StrategyFactory,
    param_grid: list[dict],
    *,
    config: ExperimentConfig,
    timeframe: str,
    instrument_key: str,
    cost_model: CostModel | None = None,
) -> WalkForwardReport:
    if not param_grid:
        raise ValueError("param_grid must contain at least one parameter set")

    cost_model = cost_model or CostModel.from_config(config.cost(instrument_key))
    wf = config.walk_forward
    embargo_bars = _embargo_bars(config, timeframe)
    starting_equity = config.account.paper_balance_usd
    rf = config.benchmark.risk_free_annual_pct / 100.0  # percent -> fraction
    min_trades = config.validation.in_sample_min_trades

    windows_idx = generate_windows(
        len(candles),
        in_sample_bars=wf.in_sample_bars,
        out_of_sample_bars=wf.out_of_sample_bars,
        step_bars=wf.step_bars,
        embargo_bars=embargo_bars,
        anchored=wf.anchored,
    )
    if not windows_idx:
        raise ValueError(
            f"no walk-forward windows fit in {len(candles)} bars "
            f"(need >= IS {wf.in_sample_bars} + embargo {embargo_bars} + OOS "
            f"{wf.out_of_sample_bars})"
        )

    report = WalkForwardReport(
        timeframe=timeframe, instrument=instrument_key, n_param_trials=len(param_grid)
    )
    all_oos_returns: list[pd.Series] = []
    all_oos_trades: list[pd.DataFrame] = []
    is_trial_sharpes: list[float] = []  # for DSR variance-across-trials estimate

    for w, (is0, is1, oos0, oos1) in enumerate(windows_idx):
        is_candles = candles.iloc[is0:is1]
        oos_candles = candles.iloc[oos0:oos1]

        # 1+2: search IS, pick best by Sharpe subject to the trade gate.
        best = None
        for params in param_grid:
            res = run_backtest(
                is_candles, factory(params),
                cost_model=cost_model, timeframe=timeframe,
                starting_equity=starting_equity,
                risk_per_trade_pct=config.account.risk_per_trade_pct,
            )
            m = M.summarize(res.trades, res.equity, starting_equity, rf_annual=rf)
            is_trial_sharpes.append(m["sharpe"] if not np.isnan(m["sharpe"]) else 0.0)
            gate_met = m["n_trades"] >= min_trades
            score = m["sharpe"] if not np.isnan(m["sharpe"]) else -np.inf
            cand = (gate_met, score, params, m)
            # Prefer gate-meeting configs; among them (or among all if none), max Sharpe.
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand

        gate_met, _, chosen_params, is_metrics = best

        # 3: evaluate chosen config OOS.
        oos_res = run_backtest(
            oos_candles, factory(chosen_params),
            cost_model=cost_model, timeframe=timeframe,
            starting_equity=starting_equity,
            risk_per_trade_pct=config.account.risk_per_trade_pct,
        )
        oos_metrics = M.summarize(oos_res.trades, oos_res.equity, starting_equity, rf_annual=rf)
        oos_returns = M.daily_returns(oos_res.equity)

        wfe = M.walk_forward_efficiency(is_metrics["cagr_pct"], oos_metrics["cagr_pct"])

        report.windows.append(
            WindowResult(
                index=w,
                is_start=is_candles.index[0], is_end=is_candles.index[-1],
                oos_start=oos_candles.index[0], oos_end=oos_candles.index[-1],
                chosen_params=chosen_params,
                is_metrics=is_metrics, oos_metrics=oos_metrics,
                wfe=wfe, oos_returns=oos_returns, oos_trades=oos_res.trades,
                is_trade_gate_met=gate_met,
            )
        )
        if not oos_returns.empty:
            all_oos_returns.append(oos_returns)
        if not oos_res.trades.empty:
            all_oos_trades.append(oos_res.trades)

    _aggregate(report, all_oos_returns, all_oos_trades, is_trial_sharpes, starting_equity, rf)
    return report


def _aggregate(
    report: WalkForwardReport,
    oos_returns: list[pd.Series],
    oos_trades: list[pd.DataFrame],
    is_trial_sharpes: list[float],
    starting_equity: float,
    rf: float,
) -> None:
    wfes = [w.wfe for w in report.windows if not np.isnan(w.wfe)]
    report.mean_wfe = float(np.mean(wfes)) if wfes else float("nan")

    if oos_returns:
        stitched = pd.concat(oos_returns).sort_index()
        stitched = stitched[~stitched.index.duplicated(keep="first")]
        # Synthetic compounded OOS equity for drawdown/sortino.
        equity = starting_equity * (1.0 + stitched).cumprod()
        trades = pd.concat(oos_trades, ignore_index=True) if oos_trades else pd.DataFrame()
        report.aggregate = {
            "oos_n_trades": int(len(trades)),
            "oos_sortino": M.sortino_ratio(stitched, rf_annual=rf),
            "oos_sharpe": M.sharpe_ratio(stitched, rf_annual=rf),
            "oos_max_drawdown_pct": float(M.max_drawdown(equity) * 100.0),
            "oos_profit_factor": M.profit_factor(trades),
            "oos_total_return_pct": float((equity.iloc[-1] / starting_equity - 1.0) * 100.0),
            "oos_return_days": int(len(stitched)),
        }
        # Deflated Sharpe on stitched OOS daily returns; N = breadth of param search.
        sr_var = float(np.var(is_trial_sharpes, ddof=1)) if len(is_trial_sharpes) > 1 else 0.0
        # Convert annualized trial-Sharpe variance to per-observation scale for DSR.
        sr_var_per_obs = sr_var / M.TRADING_DAYS_PER_YEAR
        dsr = M.deflated_sharpe_ratio(
            stitched, n_trials=report.n_param_trials, sr_variance=sr_var_per_obs
        )
        report.deflated_sharpe = {
            "dsr": dsr.dsr,
            "psr_vs_zero": dsr.psr_vs_zero,
            "n_trials": dsr.n_trials,
            "n_returns": dsr.n_returns,
            "sr_hat_non_annualized": dsr.sr_hat_non_annualized,
            "sr0_non_annualized": dsr.sr0_non_annualized,
        }
    else:
        report.aggregate = {"oos_n_trades": 0, "note": "no OOS trades generated"}
        report.deflated_sharpe = {"dsr": float("nan"), "note": "no OOS returns"}
