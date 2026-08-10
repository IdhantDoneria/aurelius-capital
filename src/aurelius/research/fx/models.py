"""Multi-currency / FX domain models (AIDP M16).

Frozen dataclasses only. M16 removes the single-currency assumption from the post-trade
stack **without forking M11 accounting**: the book of record stays the reused M11
`PortfolioState`, one per currency inside a `MultiCurrencyBook`. These models are the
immutable, currency-explicit vocabulary layered on top — every monetary quantity is
tagged with its currency, and every FX conversion carries source/target/rate/as-of/
provider/direction so nothing converts implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class CurrencyRole(str, Enum):
    """Role a currency plays for a given quantity — makes the numeraire explicit."""
    BASE = "base"                 # portfolio reporting numeraire
    TRADING = "trading"           # currency a security is priced/traded in
    SETTLEMENT = "settlement"     # currency an obligation settles in
    CASH = "cash"                 # currency a cash balance is held in
    REPORTING = "reporting"       # currency a report is expressed in


class ConversionDirection(str, Enum):
    IDENTITY = "identity"         # same currency, rate 1
    DIRECT = "direct"             # provider knew base/quote directly
    INVERSE = "inverse"           # used 1/rate of the canonical quote/base
    CROSS = "cross"               # via a pivot currency


# ── currency & rates ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Currency:
    code: str                     # ISO-4217-style 3-letter code, normalized upper

    def __post_init__(self):
        object.__setattr__(self, "code", str(self.code).strip().upper())


@dataclass(frozen=True)
class CurrencyPair:
    """Quote convention: `base/quote` = units of `quote` per one unit of `base`
    (EUR/USD = 1.10 → 1 EUR = 1.10 USD)."""
    base: str
    quote: str

    @property
    def symbol(self) -> str:
        return f"{self.base}/{self.quote}"

    def inverse(self) -> CurrencyPair:
        return CurrencyPair(self.quote, self.base)


@dataclass(frozen=True)
class FXRate:
    pair: CurrencyPair
    rate: float                   # quote per base
    as_of: date | None = None
    source: str = "unknown"

    def convert(self, amount: float) -> float:
        """Convert an amount denominated in `pair.base` into `pair.quote`."""
        return amount * self.rate

    def inverse(self) -> FXRate:
        return FXRate(self.pair.inverse(), 1.0 / self.rate, self.as_of, self.source)


@dataclass(frozen=True)
class FXRateSnapshot:
    """A dated set of rates against one base — the FX half of a valuation snapshot."""
    as_of: date | None
    base: str
    rates: dict = field(default_factory=dict)     # "CCY/BASE" -> float
    source: str = "unknown"


@dataclass(frozen=True)
class FXConversion:
    conversion_id: str
    from_currency: str
    to_currency: str
    from_amount: float            # magnitude sold, in from_currency
    to_amount: float              # magnitude bought, in to_currency
    rate: float                   # effective from->to rate (to_amount / from_amount)
    direction: ConversionDirection
    as_of: date | None
    source: str
    reason: str = "fx"


# ── cash ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CurrencyBalance:
    currency: str
    economic: float               # trade-date balance (== M11 cash for this ccy book)
    settled: float
    pending_in: float
    pending_out: float


@dataclass(frozen=True)
class MultiCurrencyCash:
    base_currency: str
    balances: dict = field(default_factory=dict)   # ccy -> CurrencyBalance
    as_of: date | None = None
    total_base_economic: float = 0.0
    total_base_settled: float = 0.0


# ── valuation ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CurrencyValuation:
    currency: str
    cash_local: float
    positions_local: float
    total_local: float
    fx_rate_to_base: float
    total_base: float
    as_of: date | None = None
    rate_source: str = "unknown"


@dataclass(frozen=True)
class MultiCurrencyPortfolioValue:
    base_currency: str
    as_of: date | None
    by_currency: dict = field(default_factory=dict)   # ccy -> CurrencyValuation
    total_base: float = 0.0
    cash_base: float = 0.0
    positions_base: float = 0.0


# ── exposure ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FXExposure:
    currency: str
    cash_exposure_base: float
    security_exposure_base: float
    settlement_exposure_base: float
    hedge_base: float
    gross_base: float
    net_base: float
    unhedged_base: float


@dataclass(frozen=True)
class FXExposureReport:
    base_currency: str
    as_of: date | None
    by_currency: dict = field(default_factory=dict)   # ccy -> FXExposure
    gross: float = 0.0            # Σ|net| over non-base currencies (base terms)
    net: float = 0.0
    long: float = 0.0
    short: float = 0.0
    largest_currency: str = ""
    largest_share: float = 0.0


# ── P&L ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FXPnL:
    """Per-currency base-P&L decomposition over a marking period:
    Δ(V·R) = R0·ΔV (local) + V0·ΔR (fx/translation) + ΔV·ΔR (interaction) — exact."""
    currency: str
    local_pnl_base: float
    fx_pnl_base: float
    interaction_base: float
    total_base: float
    realized_fx_base: float = 0.0
    unrealized_fx_base: float = 0.0


@dataclass(frozen=True)
class FXPnLReport:
    base_currency: str
    by_currency: dict = field(default_factory=dict)   # ccy -> FXPnL
    local_pnl: float = 0.0
    fx_pnl: float = 0.0
    interaction: float = 0.0
    total_pnl: float = 0.0
    realized_fx: float = 0.0
    unrealized_fx: float = 0.0
    reconciles: bool = True


# ── reconciliation ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CurrencyReconciliation:
    ok: bool
    differences: list = field(default_factory=list)
    categories: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FXReconciliationReport:
    ok: bool
    differences: list = field(default_factory=list)
    categories: dict = field(default_factory=dict)
    conversions_checked: int = 0


# ── risk / stress / hedging ──────────────────────────────────────────────────

@dataclass(frozen=True)
class FXRiskReport:
    base_currency: str
    by_currency: dict = field(default_factory=dict)   # ccy -> metrics dict
    fx_var: float = 0.0
    largest_currency: str = ""
    concentration: float = 0.0
    violations: list = field(default_factory=list)


@dataclass(frozen=True)
class FXStressScenario:
    """`shocks`: currency -> fractional move of that currency versus the base
    (+0.10 = the currency appreciates 10% against base). Base-currency shock means the
    base strengthens, translating into a matching decline of every foreign currency."""
    name: str
    shocks: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FXStressResult:
    scenario: str
    base_value: float
    stressed_base_value: float
    pnl_base: float
    pnl_fraction: float
    by_currency: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FXHedge:
    """Abstract hedge (interface for future forward/future/swap infrastructure). It
    carries a base-currency notional that offsets exposure in `currency`; it is
    represented, not priced or settled, in M16."""
    hedge_id: str
    currency: str
    notional_base: float          # + reduces long exposure in `currency`
    instrument: str = "forward"   # forward | future | swap
    rate: float | None = None
    maturity: date | None = None


# ── reports ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CashByCurrencyReport:
    base_currency: str
    as_of: date | None
    balances: dict = field(default_factory=dict)      # ccy -> CurrencyBalance
    total_base: float = 0.0


@dataclass(frozen=True)
class SettlementCurrencyReport:
    base_currency: str
    by_currency: dict = field(default_factory=dict)   # ccy -> metrics dict
    total_pending_base: float = 0.0


@dataclass(frozen=True)
class CurrencyAttributionReport:
    base_currency: str
    local_return: float
    fx_return: float
    interaction: float
    total_return: float
    by_currency: dict = field(default_factory=dict)
    reconciles: bool = True


@dataclass(frozen=True)
class MultiCurrencyPortfolioReport:
    base_currency: str
    as_of: date | None
    value: MultiCurrencyPortfolioValue
    cash: CashByCurrencyReport
    exposure: FXExposureReport
    reconciliation: FXReconciliationReport
    pnl: FXPnLReport | None = None
    n_currencies: int = 0
    n_conversions: int = 0


@dataclass(frozen=True)
class FXDiagnostics:
    n_currencies: int
    n_conversions: int
    total_base_value: float
    realized_fx_pnl: float
    fingerprint: str
