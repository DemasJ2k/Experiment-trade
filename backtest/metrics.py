"""Performance + significance metrics.

Trade/return stats: Sortino, Sharpe, max drawdown, profit factor, expectancy, win
rate, CAGR. Validation stats: walk-forward efficiency (WFE) and the Deflated Sharpe
Ratio (Bailey & López de Prado, 2014) for the multiple-testing correction.

Deflated Sharpe references:
  - Bailey, D. & López de Prado, M. (2014), "The Deflated Sharpe Ratio".
    https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
The Probabilistic Sharpe Ratio (PSR) corrects for sample length, skew and kurtosis;
the DSR additionally deflates the benchmark Sharpe by the expected maximum across the
N strategy configurations tried (selection bias).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

EULER_MASCHERONI = 0.5772156649015329
TRADING_DAYS_PER_YEAR = 252


# --------------------------------------------------------------------------- #
# Return series helpers
# --------------------------------------------------------------------------- #
def daily_returns(equity: pd.Series) -> pd.Series:
    """Resample a mark-to-market equity curve to daily simple returns."""
    if equity.empty:
        return pd.Series(dtype=float)
    daily_equity = equity.resample("1D").last().dropna()
    return daily_equity.pct_change().dropna()


# --------------------------------------------------------------------------- #
# Risk / return stats
# --------------------------------------------------------------------------- #
def sharpe_ratio(
    returns: pd.Series, *, periods_per_year: int = TRADING_DAYS_PER_YEAR, rf_annual: float = 0.0
) -> float:
    """Annualized Sharpe. ``rf_annual`` is a FRACTION (0.04 = 4%), not percent."""
    if len(returns) < 2:
        return float("nan")
    rf_per_period = rf_annual / periods_per_year
    excess = returns - rf_per_period
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(excess.mean() / sd * math.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series,
    *,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    rf_annual: float = 0.0,
    target: float = 0.0,
) -> float:
    """Annualized Sortino. ``rf_annual`` is a FRACTION (0.04 = 4%), not percent."""
    if len(returns) < 2:
        return float("nan")
    rf_per_period = rf_annual / periods_per_year
    excess = returns - rf_per_period
    downside = np.minimum(excess - target, 0.0)
    downside_dev = math.sqrt(np.mean(np.square(downside)))
    if downside_dev == 0 or np.isnan(downside_dev):
        return float("nan")
    return float(excess.mean() / downside_dev * math.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.18)."""
    if equity.empty:
        return float("nan")
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def profit_factor(trades: pd.DataFrame) -> float:
    if trades.empty:
        return float("nan")
    gains = trades.loc[trades["pnl_usd"] > 0, "pnl_usd"].sum()
    losses = -trades.loc[trades["pnl_usd"] < 0, "pnl_usd"].sum()
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def expectancy(trades: pd.DataFrame) -> float:
    """Average PnL per trade (USD)."""
    if trades.empty:
        return float("nan")
    return float(trades["pnl_usd"].mean())


def win_rate(trades: pd.DataFrame) -> float:
    if trades.empty:
        return float("nan")
    return float((trades["pnl_usd"] > 0).mean())


def total_return(equity: pd.Series, starting_equity: float) -> float:
    if equity.empty or starting_equity == 0:
        return float("nan")
    return float(equity.iloc[-1] / starting_equity - 1.0)


def cagr(equity: pd.Series, starting_equity: float) -> float:
    if equity.empty or starting_equity <= 0:
        return float("nan")
    span_days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400.0
    if span_days <= 0:
        return float("nan")
    years = span_days / 365.25
    growth = equity.iloc[-1] / starting_equity
    if growth <= 0:
        return float("nan")
    return float(growth ** (1.0 / years) - 1.0)


# --------------------------------------------------------------------------- #
# Walk-forward efficiency
# --------------------------------------------------------------------------- #
def walk_forward_efficiency(is_metric: float, oos_metric: float) -> float:
    """WFE = out-of-sample / in-sample performance (per equivalent time).

    Pass annualized returns (or any per-time metric) so window lengths are comparable.
    ~1.0 means OOS held up to IS; <0.5 flags overfitting.
    """
    if is_metric is None or oos_metric is None:
        return float("nan")
    if is_metric == 0 or np.isnan(is_metric) or np.isnan(oos_metric):
        return float("nan")
    return float(oos_metric / is_metric)


# --------------------------------------------------------------------------- #
# Probabilistic / Deflated Sharpe Ratio
# --------------------------------------------------------------------------- #
def _non_annualized_sharpe(returns: np.ndarray) -> float:
    sd = returns.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(returns.mean() / sd)


def probabilistic_sharpe_ratio(
    returns: pd.Series | np.ndarray, sr_benchmark: float = 0.0
) -> float:
    """PSR: P(true SR > sr_benchmark), correcting for n, skew and kurtosis.

    ``sr_benchmark`` is in NON-annualized (per-observation) units, same as the
    estimated Sharpe of ``returns``.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3:
        return float("nan")
    sr_hat = _non_annualized_sharpe(r)
    if np.isnan(sr_hat):
        return float("nan")
    sd = r.std(ddof=1)
    skew = float(np.mean(((r - r.mean()) / sd) ** 3))
    kurt = float(np.mean(((r - r.mean()) / sd) ** 4))  # non-excess (normal = 3)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat ** 2))
    z = (sr_hat - sr_benchmark) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """Expected maximum (non-annualized) Sharpe across ``n_trials`` independent trials.

    SR0 = sqrt(V) * [ (1-γ)·Z⁻¹(1 - 1/N) + γ·Z⁻¹(1 - 1/(N·e)) ]
    """
    if n_trials < 1 or sr_variance <= 0 or np.isnan(sr_variance):
        return float("nan")
    if n_trials == 1:
        return 0.0
    g = EULER_MASCHERONI
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(math.sqrt(sr_variance) * ((1.0 - g) * z1 + g * z2))


@dataclass(frozen=True)
class DeflatedSharpeResult:
    dsr: float                 # P(true SR > expected-max-SR-under-null)
    psr_vs_zero: float         # PSR against SR=0 benchmark
    sr_hat_non_annualized: float
    sr0_non_annualized: float  # deflated benchmark (expected max across trials)
    n_returns: int
    n_trials: int


def deflated_sharpe_ratio(
    returns: pd.Series | np.ndarray,
    *,
    sr_trials: np.ndarray | list[float] | None = None,
    n_trials: int | None = None,
    sr_variance: float | None = None,
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio for the selected strategy.

    Provide either ``sr_trials`` (the non-annualized Sharpes of ALL configurations
    tried — variance and count are derived from it) OR both ``n_trials`` and
    ``sr_variance``. Deflating with N=1 reduces the DSR to PSR-vs-zero.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    sr_hat = _non_annualized_sharpe(r)

    if sr_trials is not None:
        trials = np.asarray(list(sr_trials), dtype=float)
        n_trials = len(trials)
        sr_variance = float(np.var(trials, ddof=1)) if n_trials > 1 else 0.0
    if n_trials is None:
        n_trials = 1
    if sr_variance is None:
        sr_variance = 0.0

    sr0 = 0.0 if n_trials <= 1 else expected_max_sharpe(sr_variance, n_trials)
    dsr = probabilistic_sharpe_ratio(r, sr_benchmark=sr0)
    psr0 = probabilistic_sharpe_ratio(r, sr_benchmark=0.0)
    return DeflatedSharpeResult(
        dsr=dsr,
        psr_vs_zero=psr0,
        sr_hat_non_annualized=sr_hat,
        sr0_non_annualized=sr0,
        n_returns=n,
        n_trials=int(n_trials),
    )


# --------------------------------------------------------------------------- #
# One-shot summary
# --------------------------------------------------------------------------- #
def summarize(
    trades: pd.DataFrame,
    equity: pd.Series,
    starting_equity: float,
    *,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    rf_annual: float = 0.0,
) -> dict:
    """Assemble the standard metric block for a single backtest run."""
    rets = daily_returns(equity)
    return {
        "n_trades": int(len(trades)),
        "total_return_pct": _pct(total_return(equity, starting_equity)),
        "cagr_pct": _pct(cagr(equity, starting_equity)),
        "sharpe": sharpe_ratio(rets, periods_per_year=periods_per_year, rf_annual=rf_annual),
        "sortino": sortino_ratio(rets, periods_per_year=periods_per_year, rf_annual=rf_annual),
        "max_drawdown_pct": _pct(max_drawdown(equity)),
        "profit_factor": profit_factor(trades),
        "expectancy_usd": expectancy(trades),
        "win_rate_pct": _pct(win_rate(trades)),
        "final_equity": float(equity.iloc[-1]) if len(equity) else starting_equity,
    }


def _pct(x: float) -> float:
    return float(x * 100.0) if x is not None and not (isinstance(x, float) and np.isnan(x)) else float("nan")
