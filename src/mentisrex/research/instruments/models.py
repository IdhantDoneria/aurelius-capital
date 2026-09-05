"""Multi-asset / derivatives domain models (AIDP M17).

Frozen dataclasses + enums only. M17 removes the *equity* assumption from the book
without forking M11/M15 accounting: equities still delegate straight to the reused M15
`PostTradeEngine` (so their behaviour is byte-identical), and derivatives are layered on
top as an additive overlay. Every instrument carries an explicit contract multiplier and
a cash convention, so nothing about how a trade turns into cash is hard-coded to shares.

Vocabulary
  * contract_size  — economic multiplier (shares/contract, notional per point, face value).
  * cash convention — how a fill exchanges cash:
        PRINCIPAL  exchange notional now (equity, option premium, bond principal)
        MARGINED   exchange nothing now, only variation margin later (future, forward)
        NPV        value & settle via an injected provider (swap)
  * mark           — a per-unit price used to value a position (mark, option price, NPV/unit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class InstrumentType(StrEnum):
    EQUITY = "equity"
    FUTURE = "future"
    OPTION = "option"
    FORWARD = "forward"
    SWAP = "swap"
    BOND = "bond"


class CashConvention(StrEnum):
    PRINCIPAL = "principal"  # cash = -(qty * price * contract_size) - cost
    MARGINED = "margined"  # cash = -cost; P&L flows as variation margin
    NPV = "npv"  # valued/settled by an injected provider


class OptionRight(StrEnum):
    CALL = "call"
    PUT = "put"


class SettlementStyle(StrEnum):
    CASH = "cash"
    PHYSICAL = "physical"


class ExerciseStyle(StrEnum):
    EUROPEAN = "european"  # M17 supports European exercise only


class ExerciseStatus(StrEnum):
    OPEN = "open"
    EXERCISED = "exercised"
    ASSIGNED = "assigned"
    EXPIRED = "expired"  # expired worthless


# ── the unified instrument ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Instrument:
    """One instrument definition — the vocabulary every asset class shares."""

    instrument_id: str
    type: InstrumentType
    currency: str = "USD"
    exchange: str = ""
    contract_size: float = 1.0
    expiry: date | None = None
    calendar: str = ""
    cash_convention: CashConvention = CashConvention.PRINCIPAL
    settlement_style: SettlementStyle = SettlementStyle.CASH
    # option / derivative extras (only populated when relevant)
    underlying: str | None = None
    strike: float | None = None
    right: OptionRight | None = None
    exercise_style: ExerciseStyle = ExerciseStyle.EUROPEAN
    initial_margin_rate: float = 0.0
    maintenance_margin_rate: float = 0.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "currency", str(self.currency).strip().upper())
        if self.contract_size <= 0:
            raise ValueError(f"contract_size must be > 0, got {self.contract_size}")

    @property
    def is_derivative(self) -> bool:
        return self.type is not InstrumentType.EQUITY

    def notional(self, quantity: float, price: float) -> float:
        """Gross notional of `quantity` contracts at `price` (always positive)."""
        return abs(quantity) * price * self.contract_size


# ── positions & accounting overlay ───────────────────────────────────────────


@dataclass(frozen=True)
class InstrumentPosition:
    """Immutable snapshot of a derivative position (equities live in M11 state)."""

    instrument_id: str
    quantity: float  # signed contracts
    avg_price: float  # average entry price / premium per unit
    last_mark: float  # last mark used for MTM
    contract_size: float
    currency: str
    realized_pnl: float = 0.0  # closed-trade P&L (position currency)
    margin: float = 0.0  # posted margin requirement
    collateral: float = 0.0  # posted collateral requirement

    @property
    def notional(self) -> float:
        return abs(self.quantity) * self.last_mark * self.contract_size

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_mark * self.contract_size

    @property
    def unrealized_pnl(self) -> float:
        return (self.last_mark - self.avg_price) * self.quantity * self.contract_size


@dataclass(frozen=True)
class Greeks:
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0

    def scale(self, factor: float) -> Greeks:
        return Greeks(
            self.delta * factor,
            self.gamma * factor,
            self.theta * factor,
            self.vega * factor,
            self.rho * factor,
        )

    def __add__(self, other: Greeks) -> Greeks:
        return Greeks(
            self.delta + other.delta,
            self.gamma + other.gamma,
            self.theta + other.theta,
            self.vega + other.vega,
            self.rho + other.rho,
        )


@dataclass(frozen=True)
class MarginRequirement:
    instrument_id: str
    initial: float
    maintenance: float
    currency: str = "USD"


@dataclass(frozen=True)
class CollateralBalance:
    """Posted collateral. `cash` and `securities` are gross; `value` applies haircuts."""

    cash: float = 0.0
    securities: float = 0.0
    haircut: float = 0.0  # fraction applied to securities (0.10 = 10%)
    currency: str = "USD"

    @property
    def value(self) -> float:
        return self.cash + self.securities * (1.0 - self.haircut)


# ── lifecycle events (append-only, extend the M15 event vocabulary) ──────────


class InstrumentEventType(StrEnum):
    CREATION = "creation"
    TRADE = "trade"
    SETTLEMENT = "settlement"
    MARK_TO_MARKET = "mark_to_market"
    MARGIN_CALL = "margin_call"
    EXPIRY = "expiry"
    EXERCISE = "exercise"
    ASSIGNMENT = "assignment"
    ROLL = "roll"
    CORPORATE_ACTION = "corporate_action"
    TERMINATION = "termination"


@dataclass(frozen=True)
class InstrumentEvent:
    seq: int
    type: InstrumentEventType
    instrument_id: str
    quantity: float = 0.0
    price: float = 0.0
    cash: float = 0.0
    when: date | None = None
    detail: str = ""
    data: dict = field(default_factory=dict)
