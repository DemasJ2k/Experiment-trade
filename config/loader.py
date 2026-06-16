"""Config loader for the AI Trading Experiment.

Reads ``config/experiment.yaml`` (the pre-registered, frozen contract) and ``.env``
(secrets). Validates the YAML schema strictly and fails LOUDLY on missing keys.

Secrets are validated lazily, at the point of use, via :func:`require_env` — so the
backtest harness and tests run without network credentials, while any component that
actually touches the network fails closed if its key is missing.

Design rule: locked parameters live in the YAML, never hardcoded in modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Repo root = parent of this file's directory (config/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "experiment.yaml"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid. Always fail loudly."""


# --------------------------------------------------------------------------- #
# Typed config sections (frozen — the contract must not mutate at runtime).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AccountConfig:
    paper_balance_usd: float
    risk_per_trade_pct: float

    def __post_init__(self) -> None:
        if not (0.5 <= self.risk_per_trade_pct <= 1.0):
            raise ConfigError(
                f"account.risk_per_trade_pct must be in [0.5, 1.0], got {self.risk_per_trade_pct}"
            )


@dataclass(frozen=True)
class SampleConfig:
    verdict_trades: int
    interim_trades: int


@dataclass(frozen=True)
class RewardConfig:
    base_ratio: float
    high_confidence_ratio: float
    high_confidence_unlocked: bool


@dataclass(frozen=True)
class ValidationConfig:
    walk_forward_efficiency_min: float
    embargo_days: int
    in_sample_min_trades: int


@dataclass(frozen=True)
class WalkForwardConfig:
    in_sample_bars: int
    out_of_sample_bars: int
    step_bars: int
    anchored: bool


@dataclass(frozen=True)
class BenchmarkConfig:
    type: str
    risk_free_annual_pct: float


@dataclass(frozen=True)
class ProfitabilityConfig:
    require_beats_benchmark: bool
    sortino_min: float
    require_statistical_significance: bool
    multiple_testing_correction: str


@dataclass(frozen=True)
class SafetyConfig:
    daily_loss_breaker_pct: float
    max_drawdown_breaker_pct: float
    max_open_positions: int
    calendar_blackout_events: tuple[str, ...]
    max_api_calls_per_cycle: int
    fail_closed: bool


@dataclass(frozen=True)
class InstrumentConfig:
    key: str
    provider_symbol: str
    type: str


@dataclass(frozen=True)
class CostConfig:
    half_spread_price: float
    slippage_price: float
    commission_per_trade_usd: float


@dataclass(frozen=True)
class DataConfig:
    closed_candles_only: bool
    model_costs: bool
    provider: str
    store_dir: str
    timeframes: tuple[str, ...]
    max_history_batches: int


@dataclass(frozen=True)
class NewsConfig:
    provider: str
    lookback_days: int


@dataclass(frozen=True)
class EconomicCalendarConfig:
    source: str
    blackout_hours_before: int
    blackout_hours_after: int


@dataclass(frozen=True)
class AgentConfig:
    timeframe: str | None
    instrument: str | None


@dataclass(frozen=True)
class ExperimentConfig:
    account: AccountConfig
    sample: SampleConfig
    reward: RewardConfig
    validation: ValidationConfig
    walk_forward: WalkForwardConfig
    benchmark: BenchmarkConfig
    profitability: ProfitabilityConfig
    safety: SafetyConfig
    data: DataConfig
    instruments: dict[str, InstrumentConfig]
    costs: dict[str, CostConfig]
    news: NewsConfig
    economic_calendar: EconomicCalendarConfig
    agent: AgentConfig
    stretch_metric: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # -- convenience -------------------------------------------------------- #
    def store_path(self) -> Path:
        return (REPO_ROOT / self.data.store_dir).resolve()

    def instrument(self, key: str) -> InstrumentConfig:
        try:
            return self.instruments[key]
        except KeyError as exc:
            raise ConfigError(
                f"unknown instrument '{key}'; known: {sorted(self.instruments)}"
            ) from exc

    def cost(self, instrument_key: str) -> CostConfig:
        try:
            return self.costs[instrument_key]
        except KeyError as exc:
            raise ConfigError(
                f"no cost model for instrument '{instrument_key}'; "
                f"known: {sorted(self.costs)}"
            ) from exc


# --------------------------------------------------------------------------- #
# Loading + validation
# --------------------------------------------------------------------------- #
def _require(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise ConfigError(f"missing required config key '{ctx}.{key}'")
    return d[key]


def load_config(path: str | Path | None = None) -> ExperimentConfig:
    """Load and strictly validate the experiment config. Fails loudly if malformed."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(
            f"config file not found at {cfg_path}. Copy experiment.example.yaml to "
            f"config/experiment.yaml."
        )
    with cfg_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"config at {cfg_path} did not parse to a mapping")

    acc = _require(raw, "account", "<root>")
    smp = _require(raw, "sample", "<root>")
    rwd = _require(raw, "reward", "<root>")
    val = _require(raw, "validation", "<root>")
    wf = _require(raw, "walk_forward", "<root>")
    bmk = _require(raw, "benchmark", "<root>")
    prof = _require(raw, "profitability", "<root>")
    saf = _require(raw, "safety", "<root>")
    dat = _require(raw, "data", "<root>")
    instr = _require(raw, "instruments", "<root>")
    costs = _require(raw, "costs", "<root>")
    nws = _require(raw, "news", "<root>")
    econ = _require(raw, "economic_calendar", "<root>")
    agt = _require(raw, "agent", "<root>")

    instruments = {
        key: InstrumentConfig(
            key=key,
            provider_symbol=_require(v, "provider_symbol", f"instruments.{key}"),
            type=_require(v, "type", f"instruments.{key}"),
        )
        for key, v in instr.items()
    }
    cost_models = {
        key: CostConfig(
            half_spread_price=float(_require(v, "half_spread_price", f"costs.{key}")),
            slippage_price=float(_require(v, "slippage_price", f"costs.{key}")),
            commission_per_trade_usd=float(
                _require(v, "commission_per_trade_usd", f"costs.{key}")
            ),
        )
        for key, v in costs.items()
    }

    # Every instrument must have a cost model (we always model costs).
    missing_costs = set(instruments) - set(cost_models)
    if missing_costs:
        raise ConfigError(f"instruments without a cost model: {sorted(missing_costs)}")

    config = ExperimentConfig(
        account=AccountConfig(
            paper_balance_usd=float(_require(acc, "paper_balance_usd", "account")),
            risk_per_trade_pct=float(_require(acc, "risk_per_trade_pct", "account")),
        ),
        sample=SampleConfig(
            verdict_trades=int(_require(smp, "verdict_trades", "sample")),
            interim_trades=int(_require(smp, "interim_trades", "sample")),
        ),
        reward=RewardConfig(
            base_ratio=float(_require(rwd, "base_ratio", "reward")),
            high_confidence_ratio=float(_require(rwd, "high_confidence_ratio", "reward")),
            high_confidence_unlocked=bool(
                _require(rwd, "high_confidence_unlocked", "reward")
            ),
        ),
        validation=ValidationConfig(
            walk_forward_efficiency_min=float(
                _require(val, "walk_forward_efficiency_min", "validation")
            ),
            embargo_days=int(_require(val, "embargo_days", "validation")),
            in_sample_min_trades=int(_require(val, "in_sample_min_trades", "validation")),
        ),
        walk_forward=WalkForwardConfig(
            in_sample_bars=int(_require(wf, "in_sample_bars", "walk_forward")),
            out_of_sample_bars=int(_require(wf, "out_of_sample_bars", "walk_forward")),
            step_bars=int(_require(wf, "step_bars", "walk_forward")),
            anchored=bool(_require(wf, "anchored", "walk_forward")),
        ),
        benchmark=BenchmarkConfig(
            type=_require(bmk, "type", "benchmark"),
            risk_free_annual_pct=float(_require(bmk, "risk_free_annual_pct", "benchmark")),
        ),
        profitability=ProfitabilityConfig(
            require_beats_benchmark=bool(
                _require(prof, "require_beats_benchmark", "profitability")
            ),
            sortino_min=float(_require(prof, "sortino_min", "profitability")),
            require_statistical_significance=bool(
                _require(prof, "require_statistical_significance", "profitability")
            ),
            multiple_testing_correction=_require(
                prof, "multiple_testing_correction", "profitability"
            ),
        ),
        safety=SafetyConfig(
            daily_loss_breaker_pct=float(
                _require(saf, "daily_loss_breaker_pct", "safety")
            ),
            max_drawdown_breaker_pct=float(
                _require(saf, "max_drawdown_breaker_pct", "safety")
            ),
            max_open_positions=int(_require(saf, "max_open_positions", "safety")),
            calendar_blackout_events=tuple(
                _require(saf, "calendar_blackout_events", "safety")
            ),
            max_api_calls_per_cycle=int(_require(saf, "max_api_calls_per_cycle", "safety")),
            fail_closed=bool(_require(saf, "fail_closed", "safety")),
        ),
        data=DataConfig(
            closed_candles_only=bool(_require(dat, "closed_candles_only", "data")),
            model_costs=bool(_require(dat, "model_costs", "data")),
            provider=_require(dat, "provider", "data"),
            store_dir=_require(dat, "store_dir", "data"),
            timeframes=tuple(_require(dat, "timeframes", "data")),
            max_history_batches=int(_require(dat, "max_history_batches", "data")),
        ),
        instruments=instruments,
        costs=cost_models,
        news=NewsConfig(
            provider=_require(nws, "provider", "news"),
            lookback_days=int(_require(nws, "lookback_days", "news")),
        ),
        economic_calendar=EconomicCalendarConfig(
            source=_require(econ, "source", "economic_calendar"),
            blackout_hours_before=int(
                _require(econ, "blackout_hours_before", "economic_calendar")
            ),
            blackout_hours_after=int(
                _require(econ, "blackout_hours_after", "economic_calendar")
            ),
        ),
        agent=AgentConfig(
            timeframe=agt.get("timeframe"),
            instrument=agt.get("instrument"),
        ),
        stretch_metric=raw.get("stretch_metric", {}),
        raw=raw,
    )

    # Sanity: closed-candles-only and model-costs are non-negotiable design rules.
    if not config.data.closed_candles_only:
        raise ConfigError("data.closed_candles_only must be true (no look-ahead rule)")
    if not config.data.model_costs:
        raise ConfigError("data.model_costs must be true (costs are always modelled)")
    return config


# --------------------------------------------------------------------------- #
# Secrets (.env) — validated lazily at point of use, fail-closed.
# --------------------------------------------------------------------------- #
_ENV_LOADED = False


def load_env(env_path: str | Path | None = None, *, override: bool = False) -> None:
    """Load .env into the process environment once (idempotent)."""
    global _ENV_LOADED
    if _ENV_LOADED and not override:
        return
    path = Path(env_path) if env_path else DEFAULT_ENV_PATH
    load_dotenv(dotenv_path=path, override=override)
    _ENV_LOADED = True


def require_env(name: str, env_path: str | Path | None = None) -> str:
    """Return a required secret from the environment, or fail loudly.

    Use this at the boundary where a network call happens (fail-closed): a missing
    or blank secret raises rather than silently proceeding.
    """
    load_env(env_path)
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"required secret '{name}' is missing or blank. Set it in .env "
            f"(copy env_example.txt to .env and fill it in)."
        )
    return value


def get_run_mode(env_path: str | Path | None = None) -> str:
    """Return RUN_MODE, defaulting to 'backtest'. Refuses 'live' (paper/demo only)."""
    load_env(env_path)
    mode = os.environ.get("RUN_MODE", "backtest").strip().lower()
    if mode == "live":
        raise ConfigError(
            "RUN_MODE=live is forbidden. This experiment is paper/demo only."
        )
    if mode not in {"backtest", "paper"}:
        raise ConfigError(f"RUN_MODE must be 'backtest' or 'paper', got '{mode}'")
    return mode


if __name__ == "__main__":  # quick manual smoke check
    cfg = load_config()
    print("Loaded config OK.")
    print(f"  instruments : {sorted(cfg.instruments)}")
    print(f"  timeframes  : {list(cfg.data.timeframes)}")
    print(f"  provider    : {cfg.data.provider}")
    print(f"  run_mode    : {get_run_mode()}")
