"""Every tunable in the Mentis Rex Programme, in one place, versioned and fingerprinted.

This module is the single source of truth for every numeric knob the programme
uses: universe screens, signal windows, allocator weights, cost and financing
rates, risk thresholds, execution parameters, and the ten sleeve definitions.
Nothing downstream (`signals.py`, `sleeves.py`, `allocator.py`, `risk.py`,
`execution.py`, `backtest.py`, `cli.py`) hard-codes a parameter; every one of
them is read off a `ProgrammeConfig` instance built here.

`ProgrammeConfig.fingerprint()` hashes every field into a 16-character digest
that is logged on every live run and stamped into every backtest result (spec
Table 26). Two runs with the same fingerprint used the same parameters. If
live performance changes, the fingerprint tells you in one comparison whether
a config edit is responsible, or whether it can be ruled out and the change
has to be explained some other way (data, market regime, a code bug).

Defaults are transcribed from `US Equity Systematic Programme v3.0 Full
Specification`, principally sections 2.2 (allocator), 2.3 (financing), 3.3
(sleeves), 4.2/4.4 (leverage ladder, Table 7), 5 (costs), 10 (circuit
breakers, Table 16) and 14 (order of operations). A value with no spec
citation is marked `# NOT in spec` and was never fabricated to look
authoritative.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, field, replace
from http import HTTPStatus
from pathlib import Path

from mentisrex.core.errors import MentisrexError


class ProgrammeError(MentisrexError):
    """Base class for every error raised inside `mentisrex.programme`."""

    http_status = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = "PROGRAMME_ERROR"


class DataQualityError(ProgrammeError):
    """A quality-gate FATAL condition fired (spec Table 15 / §14.2 09:15):
    stale panel, too many missing symbols, a benchmark gap, or universe
    collapse. No orders may be built while this stands."""

    http_status = HTTPStatus.SERVICE_UNAVAILABLE
    error_code = "PROGRAMME_DATA_QUALITY"


class RiskHaltError(ProgrammeError):
    """A HALT-severity circuit breaker fired (spec Table 16). Trading is
    frozen; there is deliberately no automatic path back (spec §10.1)."""

    http_status = HTTPStatus.CONFLICT
    error_code = "PROGRAMME_RISK_HALT"


class ConfigError(ProgrammeError):
    """Configuration is invalid: an unknown rung name, an unknown
    dotted-path override, or an unparseable config file."""

    http_status = HTTPStatus.BAD_REQUEST
    error_code = "PROGRAMME_CONFIG_ERROR"


@dataclass(frozen=True)
class UniverseConfig:
    tickers_file: str = "config/universe_us.txt"  # one ticker per line, '#' comments
    benchmark: str = "SPY"
    min_dollar_volume: float = 3_000_000.0  # 21-day median, spec §5.1
    min_history_days: int = 252
    min_price: float = 0.0  # NOT in spec; 0.0 = disabled
    max_staleness_days: int = 3  # business days
    min_eligible_names: int = 150  # UNIVERSE_COLLAPSE, spec Table 16


@dataclass(frozen=True)
class SignalConfig:
    # S1 multi-horizon trend (spec §3.3)
    trend_ma_windows: tuple[int, ...] = (50, 100, 150, 200)
    trend_return_windows: tuple[int, ...] = (63, 126, 252)
    # S2 volatility-managed exposure
    vol_target: float = 0.16
    vol_window: int = 63
    vol_exposure_floor: float = 0.4
    vol_exposure_cap: float = 1.8
    # S3 breadth timing
    breadth_ma_window: int = 200
    breadth_z_window: int = 504
    # S4 panic reversal
    panic_fast_window: int = 5
    panic_slow_window: int = 63
    panic_trigger_ratio: float = 1.40
    panic_return_window: int = 3
    panic_return_threshold: float = -0.02
    panic_max_hold_days: int = 42
    panic_regime_ma_window: int = 200
    panic_regime_drawdown: float = -0.15  # suppress if index < 15% below 200DMA
    # S5 momentum
    momentum_lookback: int = 231  # days t-231 .. t-21
    momentum_skip: int = 21
    # S6 residual momentum
    residual_beta_window: int = 252
    # S7 information discreteness
    id_weight: float = 0.5
    id_clip: float = 2.0
    # S8 Amihud illiquidity
    amihud_window: int = 21
    # S9 relative volume
    relvol_fast_window: int = 21
    relvol_slow_window: int = 252
    # S10 conditional reversal
    reversal_window: int = 5
    reversal_vol_window: int = 63
    reversal_liquid_fraction: float = 0.5


@dataclass(frozen=True)
class SleeveConfig:
    name: str  # "S1" ... "S10"
    kind: str  # "directional" | "cross_sectional"
    hold_days: int
    label: str  # human-readable, e.g. "Multi-horizon time-series trend"


@dataclass(frozen=True)
class AllocatorConfig:
    k_core: float = 4.00
    k_satellite: float = 3.60
    gross_cap: float = 2.75
    satellite_vol_target: float = 0.10
    satellite_vol_window: int = 63
    satellite_scalar_floor: float = 0.30
    satellite_scalar_cap: float = 2.50
    max_position: float = 0.20  # single names, spec §2.2
    max_position_benchmark: float = 3.00


@dataclass(frozen=True)
class CostConfig:
    one_way_bps: float = 5.0
    min_order_usd: float = 250.0  # spec Table 27, 15:42


@dataclass(frozen=True)
class FinancingConfig:
    margin_spread: float = 0.0150
    borrow_fee: float = 0.0040
    rebate_spread: float = 0.0100
    trading_days: int = 252


@dataclass(frozen=True)
class RiskConfig:
    drawdown_warn: float = 0.20
    drawdown_derisk: float = 0.28
    drawdown_halt: float = 0.34
    daily_loss_warn: float = 0.05
    daily_loss_halt: float = 0.10
    vol_ceiling: float = 0.45
    vol_ceiling_window: int = 21
    gross_hard: float = 3.00
    net_hard: float = 2.50
    position_hard: float = 0.25
    turnover_spike: float = 0.60
    cost_divergence_bps: float = 5.0
    derisk_multiplier: float = 0.5
    sleeve_health_sharpe: float = -1.0
    sleeve_health_months: int = 3
    sleeve_health_multiplier: float = 0.5  # never zero, spec Table 15


@dataclass(frozen=True)
class ExecutionConfig:
    signal_to_trade_lag: int = 2
    moc_deadline_et: str = "15:50"
    reconcile_drift_bps: float = 25.0  # per name, of NAV


@dataclass(frozen=True)
class Rung:
    name: str
    k_core: float
    k_satellite: float
    gross_cap: float


RUNGS: dict[str, Rung] = {  # spec Table 7 verbatim
    "deploy": Rung("deploy", 4.00, 1.60, 1.00),
    "conservative": Rung("conservative", 4.00, 1.60, 1.50),
    "mandate": Rung("mandate", 4.00, 2.40, 2.00),
    "standard": Rung("standard", 4.00, 3.00, 2.50),
    "recommended": Rung("recommended", 4.00, 3.60, 2.75),
    "aggressive": Rung("aggressive", 4.00, 4.00, 3.00),
}

RAMP: tuple[float, ...] = (1.00, 1.75, 2.25, 2.75)  # spec §10.2, one step/quarter

# Ten sleeves, spec Table 3 (name, type, hold) and §3.3 (label = table's sleeve name).
SLEEVES: tuple[SleeveConfig, ...] = (
    SleeveConfig("S1", "directional", 1, "Multi-horizon time-series trend"),
    SleeveConfig("S2", "directional", 1, "Volatility-managed market exposure"),
    SleeveConfig("S3", "directional", 1, "Cross-sectional breadth timing"),
    SleeveConfig("S4", "directional", 1, "Volatility term-structure panic reversal"),
    SleeveConfig("S5", "cross_sectional", 10, "Cross-sectional 12-1 momentum"),
    SleeveConfig("S6", "cross_sectional", 10, "Residual (beta-adjusted) momentum"),
    SleeveConfig("S7", "cross_sectional", 10, "Information-discreteness momentum"),
    SleeveConfig("S8", "cross_sectional", 63, "Amihud illiquidity premium"),
    SleeveConfig("S9", "cross_sectional", 21, "Relative-volume attention"),
    SleeveConfig("S10", "cross_sectional", 21, "Conditional short-horizon reversal"),
)
CORE_SLEEVES: tuple[str, ...] = ("S1", "S2", "S3", "S4")
SATELLITE_SLEEVES: tuple[str, ...] = ("S5", "S6", "S7", "S8", "S9", "S10")


def _jsonable(value: object) -> object:
    """Recursively convert tuples (and nested tuples/dicts) to lists so
    `json.dumps` output is canonical regardless of the container types
    `dataclasses.asdict` happened to preserve."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class ProgrammeConfig:
    version: str = "3.0.0"
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    signals: SignalConfig = field(default_factory=SignalConfig)
    allocator: AllocatorConfig = field(default_factory=AllocatorConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    financing: FinancingConfig = field(default_factory=FinancingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    sleeves: tuple[SleeveConfig, ...] = field(default_factory=lambda: SLEEVES)
    data_dir: str = "data/programme"
    state_dir: str = "state/programme"

    def fingerprint(self) -> str:
        """SHA-256 of the canonical JSON of every field, first 16 hex chars.
        Logged on every run (spec Table 26)."""
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        """`dataclasses.asdict(self)` with every tuple converted to a list so
        the JSON serialisation is canonical (and thus so is the fingerprint)."""
        return _jsonable(asdict(self))

    def with_rung(self, rung: str) -> ProgrammeConfig:
        """Return a copy with k_core / k_satellite / gross_cap from RUNGS[rung]."""
        chosen = RUNGS.get(rung)
        if chosen is None:
            valid = ", ".join(sorted(RUNGS))
            raise ConfigError(f"unknown rung {rung!r}; valid rungs: {valid}")
        new_allocator = replace(
            self.allocator,
            k_core=chosen.k_core,
            k_satellite=chosen.k_satellite,
            gross_cap=chosen.gross_cap,
        )
        return replace(self, allocator=new_allocator)

    def with_overrides(self, **kwargs: object) -> ProgrammeConfig:
        """Dotted-path overrides, e.g. with_overrides(**{"costs.one_way_bps": 10.0}).
        Used by the stress harness. Paths are either a top-level field name
        (e.g. "data_dir") or exactly one level of nesting ("section.field").
        Raises ConfigError on any path that doesn't resolve to a real field."""
        section_updates: dict[str, dict[str, object]] = {}
        top_level: dict[str, object] = {}
        for path, value in kwargs.items():
            if "." in path:
                section, _, field_name = path.partition(".")
                if "." in field_name:
                    raise ConfigError(
                        f"unsupported override path {path!r}: only one level of "
                        "nesting ('section.field') is supported"
                    )
                sub = getattr(self, section, None)
                if sub is None or not hasattr(sub, field_name):
                    raise ConfigError(f"unknown config override path: {path!r}")
                section_updates.setdefault(section, {})[field_name] = value
            else:
                if not hasattr(self, path):
                    raise ConfigError(f"unknown config override path: {path!r}")
                top_level[path] = value

        result = self
        for section, updates in section_updates.items():
            new_sub = replace(getattr(result, section), **updates)
            result = replace(result, **{section: new_sub})
        if top_level:
            result = replace(result, **top_level)
        return result


def _read_overrides(path: str) -> dict[str, object]:
    """Read a flat dict of dotted-path overrides from a `.toml` or `.json` file."""
    file_path = Path(path)
    if file_path.suffix == ".toml":
        with file_path.open("rb") as fh:
            return tomllib.load(fh)
    if file_path.suffix == ".json":
        with file_path.open(encoding="utf-8") as fh:
            return json.load(fh)
    raise ConfigError(
        f"unsupported config file extension {file_path.suffix!r} (use .toml or .json)"
    )


def load_config(path: str | None = None, rung: str = "recommended") -> ProgrammeConfig:
    """Load defaults, apply optional TOML/JSON overrides from `path`, apply rung."""
    config = ProgrammeConfig()
    if path is not None:
        config = config.with_overrides(**_read_overrides(path))
    return config.with_rung(rung)
