"""Value types for the Phase-7 risk system + the limit thresholds that gate a trade.

Kept free of engine/state imports so the verdict types stay pure and importable
everywhere (strategy, execution, tests). All limits live in one frozen dataclass —
these are the calibration knobs a Chief Risk Officer tunes per desk / asset class.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal


class RiskDecision(enum.StrEnum):
    APPROVE = "approve"  # order passes every check as-is
    MODIFY = "modify"  # order too large on one axis; clamp quantity down and pass
    REJECT = "reject"  # hard breach; no order should reach execution


@dataclass(frozen=True)
class RiskLimits:
    """Pre-trade + portfolio thresholds. Every value is a tunable knob.

    Fractions are of NAV unless noted. Defaults are conservative institutional
    starting points — a CRO raises/lowers per mandate.
    """

    max_position_pct: Decimal = Decimal("0.10")  # single name <= 10% NAV
    max_gross_leverage: Decimal = Decimal("1.5")  # sum|mv| / NAV <= 1.5x
    max_participation_pct: Decimal = Decimal("0.20")  # order <= 20% of ADV (fillable)
    daily_loss_limit: Decimal = Decimal("0.03")  # -3% day trips the kill switch
    max_drawdown_halt: Decimal = Decimal("0.20")  # -20% peak-to-trough trips it
    max_sector_pct: Decimal = Decimal("0.30")  # any sector <= 30% of gross
    max_name_concentration: Decimal = Decimal("0.10")  # post-trade name weight cap
    max_hhi: Decimal = Decimal("0.20")  # Herfindahl concentration ceiling
    single_trade_max_loss_pct: Decimal = Decimal("0.02")  # loss-to-stop <= 2% NAV
    var_confidence: float = 0.95  # parametric VaR confidence


@dataclass
class RiskVerdict:
    """The gatekeeper's answer. decision drives what execution receives."""

    decision: RiskDecision
    reasons: list[str] = field(default_factory=list)
    modified_quantity: Decimal | None = None  # set only when decision is MODIFY

    @property
    def approved(self) -> bool:
        return self.decision is not RiskDecision.REJECT

    @classmethod
    def approve(cls) -> RiskVerdict:
        return cls(RiskDecision.APPROVE)

    @classmethod
    def reject(cls, reason: str) -> RiskVerdict:
        return cls(RiskDecision.REJECT, [reason])

    @classmethod
    def modify(cls, qty: Decimal, reason: str) -> RiskVerdict:
        return cls(RiskDecision.MODIFY, [reason], modified_quantity=qty)


@dataclass
class RiskReport:
    """Portfolio-level monitoring snapshot (measurement, not a gate)."""

    annualized_volatility: float
    current_drawdown: float
    value_at_risk: float  # 1-day parametric VaR, currency units
    gross_leverage: float
    net_leverage: float
    herfindahl: float  # sum(w_i^2) on gross weights
    avg_pairwise_correlation: float
    portfolio_beta: float | None
    sector_exposure: dict[str, float] = field(default_factory=dict)
    breaches: list[str] = field(default_factory=list)


@dataclass
class StressResult:
    scenario: str
    nav_before: float
    nav_after: float
    pnl: float  # nav_after - nav_before
    stressed_var: float | None = None  # for the vol-spike scenario
    liquidation_days: float | None = None  # for the liquidity scenario
    survives: bool = True  # NAV stays positive + within DD halt
    detail: str = ""
