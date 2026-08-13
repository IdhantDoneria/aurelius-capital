"""Institutional Risk Engine domain models (AIDP M13).

Frozen dataclasses + enums. The Risk Engine holds no mutable portfolio state — it
reads weights / returns / prices supplied by the caller (reusing M11 `PortfolioState`
or M12 broker state) and returns immutable reports. "Canonical" M13 objects live
here; the legacy Platform-Track `mentisrex.risk` models are historical and untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class RiskDecision(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_WARNING = "approve_with_warning"
    REJECT = "reject"


# ── limits / violations ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskLimit:
    name: str
    limit: float
    kind: str = "max"                     # max | min
    severity: str = "hard"                # hard (reject) | soft (warn)


@dataclass(frozen=True)
class RiskViolation:
    limit_name: str
    observed: float
    limit: float
    kind: str
    severity: str
    security_id: str | None = None

    @property
    def message(self) -> str:
        op = ">" if self.kind == "max" else "<"
        who = f" [{self.security_id}]" if self.security_id else ""
        return f"{self.limit_name}{who} {self.observed:.4g} {op} {self.limit:.4g} ({self.severity})"


# ── analytics reports ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExposureReport:
    gross: float
    net: float
    long: float
    short: float
    cash: float
    n_long: int
    n_short: int
    sector: dict = field(default_factory=dict)      # classification interfaces
    industry: dict = field(default_factory=dict)
    country: dict = field(default_factory=dict)
    currency: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ConcentrationReport:
    herfindahl: float
    effective_holdings: float
    largest_weight: float
    largest_contribution: float
    top5_weight: float


@dataclass(frozen=True)
class FactorExposure:
    model: str
    betas: dict                            # factor -> beta
    factor_contribution: dict             # factor -> variance contribution
    factor_risk: float                    # systematic vol
    specific_risk: float                  # idiosyncratic vol
    r_squared: float


@dataclass(frozen=True)
class VaRReport:
    method: str                           # historical | parametric
    horizon_days: int
    var: dict                             # confidence -> VaR (positive loss fraction)
    expected_shortfall: dict              # confidence -> ES
    volatility: float


@dataclass(frozen=True)
class StressScenario:
    name: str
    market_shock: float = 0.0             # portfolio-wide return shock
    sector_shocks: dict = field(default_factory=dict)
    vol_multiplier: float = 1.0
    liquidity_multiplier: float = 1.0     # ADV reduction (fraction remaining)
    factor_shocks: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StressResult:
    scenario: str
    pnl_fraction: float                   # portfolio P&L under the shock
    stressed_value: float
    breached: bool


@dataclass(frozen=True)
class StressTestReport:
    results: list                         # list[StressResult]
    worst_scenario: str
    worst_pnl_fraction: float


@dataclass(frozen=True)
class DrawdownReport:
    max_drawdown: float
    avg_drawdown: float
    current_drawdown: float
    max_recovery_days: float
    time_underwater_frac: float
    rolling_max_drawdown: float
    halt_triggered: bool


@dataclass(frozen=True)
class LiquidityReport:
    avg_participation: float
    max_participation: float
    days_to_liquidate: dict               # security_id -> days
    max_days_to_liquidate: float
    illiquid_weight: float                # weight in names > liquidation_threshold days
    liquidity_signal: str


@dataclass(frozen=True)
class CapacityReport:
    capacity_usd: float
    aum_usd: float
    utilization: float
    capacity_signal: str


# ── monitoring ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskAlert:
    as_of: date | None
    kind: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True)
class RiskEvent:
    as_of: date | None
    kind: str                             # limit_breach | drawdown_breach | vol_spike | ...
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RiskSnapshot:
    as_of: date | None
    volatility: float
    gross: float
    net: float
    var_95: float
    herfindahl: float
    max_drawdown: float
    n_violations: int


# ── top-level reports ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskReport:
    as_of: date | None
    decision: RiskDecision
    volatility: float
    exposure: ExposureReport
    concentration: ConcentrationReport
    var: VaRReport | None
    factor: FactorExposure | None
    drawdown: DrawdownReport | None
    liquidity: LiquidityReport | None
    capacity: CapacityReport | None
    violations: list = field(default_factory=list)          # list[RiskViolation]
    warnings: list = field(default_factory=list)
    risk_contribution: dict = field(default_factory=dict)   # security_id -> pct risk
    metadata: dict = field(default_factory=dict)
    generated_at: datetime | None = None


@dataclass(frozen=True)
class PortfolioHealthReport:
    healthy: bool
    decision: RiskDecision
    score: float                          # 0..100 composite health
    reasons: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeploymentRiskDecision:
    deployable: bool
    risk_decision: RiskDecision
    m9_verdict: str
    reasons: list = field(default_factory=list)


@dataclass(frozen=True)
class RiskValidationResult:
    ok: bool
    health: PortfolioHealthReport
    deployment: DeploymentRiskDecision
    risk_report: dict = field(default_factory=dict)
    generated_at: datetime | None = None
