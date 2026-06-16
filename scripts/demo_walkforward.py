"""Demo: run the full walk-forward harness on SYNTHETIC data and print/save a report.

This satisfies the ROADMAP Phase-1 definition of done — running the harness on a
sample strategy produces a walk-forward report with WFE + out-of-sample metrics +
multiple-testing-corrected significance (Deflated Sharpe).

SYNTHETIC DATA ONLY: the random-walk series carries no real edge, so a no-graduate
verdict here is expected and correct. This validates plumbing, not a strategy.

Usage:
    python -m scripts.demo_walkforward
"""

from __future__ import annotations

import json
from pathlib import Path

from backtest.strategies import sma_cross_factory
from backtest.walk_forward import run_walk_forward
from config.loader import REPO_ROOT, load_config
from data.synthetic import synthetic_candles

PARAM_GRID = [
    {"fast": 10, "slow": 30, "atr_mult": 2.0, "reward": 2.0},
    {"fast": 15, "slow": 40, "atr_mult": 2.5, "reward": 2.0},
    {"fast": 20, "slow": 50, "atr_mult": 3.0, "reward": 3.0},
    {"fast": 8, "slow": 24, "atr_mult": 1.5, "reward": 2.0},
]


def _fmt(x) -> str:
    if isinstance(x, float):
        return "nan" if x != x else f"{x:,.3f}"
    return str(x)


def render(report) -> str:
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("WALK-FORWARD REPORT (SYNTHETIC DATA — plumbing validation, no real edge)")
    lines.append("=" * 78)
    lines.append(f"instrument={report.instrument}  timeframe={report.timeframe}  "
                 f"param_trials={report.n_param_trials}")
    lines.append("")
    lines.append(f"{'win':>3} {'IS_CAGR%':>9} {'OOS_CAGR%':>10} {'WFE':>7} "
                 f"{'OOS_trades':>10} {'IS_gate':>8}  chosen")
    for w in report.windows:
        lines.append(
            f"{w.index:>3} {_fmt(w.is_metrics['cagr_pct']):>9} "
            f"{_fmt(w.oos_metrics['cagr_pct']):>10} {_fmt(w.wfe):>7} "
            f"{w.oos_metrics['n_trades']:>10} {str(w.is_trade_gate_met):>8}  {w.chosen_params}"
        )
    lines.append("")
    lines.append(f"mean WFE                 : {_fmt(report.mean_wfe)}  "
                 f"(threshold {load_config().validation.walk_forward_efficiency_min})")
    lines.append("-- aggregate out-of-sample --")
    for k, v in report.aggregate.items():
        lines.append(f"  {k:<24}: {_fmt(v)}")
    lines.append("-- multiple-testing correction (Deflated Sharpe) --")
    for k, v in report.deflated_sharpe.items():
        lines.append(f"  {k:<24}: {_fmt(v)}")
    return "\n".join(lines)


def main() -> None:
    config = load_config()
    timeframe = "1day"
    instrument_key = "xauusd"

    # Enough daily bars for several rolling windows given IS/OOS/embargo in config.
    candles = synthetic_candles(3600, timeframe=timeframe, seed=11)

    report = run_walk_forward(
        candles, sma_cross_factory, PARAM_GRID,
        config=config, timeframe=timeframe, instrument_key=instrument_key,
    )
    text = render(report)
    print(text)

    out_dir = Path(REPO_ROOT) / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "walk_forward_demo.txt").write_text(text + "\n", encoding="utf-8")
    payload = {
        "instrument": report.instrument,
        "timeframe": report.timeframe,
        "mean_wfe": report.mean_wfe,
        "aggregate": report.aggregate,
        "deflated_sharpe": report.deflated_sharpe,
        "n_windows": len(report.windows),
    }
    (out_dir / "walk_forward_demo.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved report to {out_dir}/walk_forward_demo.txt(.json)")


if __name__ == "__main__":
    main()
