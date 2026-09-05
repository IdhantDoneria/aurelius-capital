"""Simulation domain models (AIDP M11).

Immutable dataclasses. Mutable accounting lives only inside PortfolioState during
the run; everything surfaced to the caller (snapshots, reports, results) is frozen
and carries an `assumptions`/`metadata` note where a modelling choice was made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Holding:
    security_id: str
    shares: float  # signed: + long, − short
    cost_basis: float  # average entry price of the OPEN position
    price: float = 0.0  # last mark
    realized_pnl: float = 0.0  # cumulative realized on this security
    opened_at: date | None = None

    @property
    def market_value(self) -> float:
        return self.shares * self.price

    @property
    def unrealized_pnl(self) -> float:
        return (self.price - self.cost_basis) * self.shares


@dataclass(frozen=True)
class Order:
    security_id: str
    quantity: float  # signed target delta in shares
    order_type: str = "market"  # market | limit (limit = interface only)
    limit_price: float | None = None


@dataclass(frozen=True)
class Fill:
    security_id: str
    quantity: float  # signed executed shares
    price: float  # execution price
    cost: float  # transaction cost (commission+spread+slippage+impact)
    notional: float  # quantity * price (signed)


@dataclass(frozen=True)
class Trade:
    security_id: str
    quantity: float
    price: float
    cost: float
    notional: float
    date: date | None = None
    kind: str = "rebalance"  # rebalance | entry | exit | reduce


@dataclass(frozen=True)
class EquityPoint:
    date: date
    value: float  # total portfolio value (cash + positions)
    cash: float
    gross_exposure: float
    net_exposure: float


@dataclass(frozen=True)
class PortfolioSnapshot:
    date: date
    value: float
    cash: float
    holdings: dict  # security_id → weight
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    n_positions: int
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RebalanceEvent:
    date: date
    n_trades: int
    turnover: float
    total_cost: float
    reason: str


@dataclass(frozen=True)
class CostReport:
    total_cost: float
    linear_cost: float
    impact_cost: float
    cost_bps_of_traded: float
    cost_drag_annualized: float


@dataclass(frozen=True)
class TurnoverReport:
    annualized_turnover: float
    total_two_way_turnover: float
    avg_holding_days: float
    n_trades: int


@dataclass(frozen=True)
class ExposureReport:
    avg_gross: float
    avg_net: float
    avg_long: float
    avg_short: float
    avg_cash_weight: float
    max_gross: float


@dataclass(frozen=True)
class DrawdownReport:
    max_drawdown: float
    avg_drawdown: float
    max_recovery_days: float
    time_underwater_frac: float


@dataclass(frozen=True)
class CapacityReport:
    avg_participation: float
    max_participation: float
    capacity_signal: str


@dataclass(frozen=True)
class RiskSnapshot:
    date: date
    volatility: float
    gross_leverage: float
    net_leverage: float
    concentration_hhi: float
    largest_weight: float
    effective_holdings: float


@dataclass(frozen=True)
class AttributionReport:
    security_contribution: dict
    sector_contribution: dict
    cost_drag: float
    cash_drag: float
    turnover_drag: float
    total_return: float
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationSummary:
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    calmar: float
    omega: float
    max_drawdown: float
    avg_drawdown: float
    hit_rate: float
    profit_factor: float
    gain_loss_ratio: float
    annualized_turnover: float
    avg_holding_days: float
    total_cost: float
    cost_drag_annualized: float
    final_value: float
    n_rebalances: int
    n_periods: int


@dataclass(frozen=True)
class SimulationMetadata:
    initial_capital: float
    start_date: date | None
    end_date: date | None
    n_periods: int
    n_rebalances: int
    rebalance_policy: str
    execution_model: str
    cost_model: dict
    allow_short: bool
    config: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationResult:
    summary: SimulationSummary
    metadata: SimulationMetadata
    equity_curve: list[EquityPoint]
    snapshots: list[PortfolioSnapshot]
    rebalance_events: list[RebalanceEvent]
    trades: list[Trade]
    cost_report: CostReport
    turnover_report: TurnoverReport
    exposure_report: ExposureReport
    drawdown_report: DrawdownReport
    capacity_report: CapacityReport
    risk_timeline: list[RiskSnapshot]
    attribution: AttributionReport
    diagnostics: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    generated_at: datetime | None = None
