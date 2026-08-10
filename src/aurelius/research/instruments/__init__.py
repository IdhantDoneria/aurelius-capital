"""Multi-Asset & Derivatives Accounting Engine (AIDP M17).

A general instrument framework layered additively over M11–M16. Equities delegate straight
to the reused M15 `PostTradeEngine` (byte-identical behaviour); futures, options, forwards,
swaps and bonds get a derivative overlay — contract-aware positions, margin, collateral,
mark-to-market, expiry/exercise/assignment — while every cash flow still runs through the
single M11 ledger. Pricing, Greeks and yields are dependency-injected; risk feeds M13, FX
uses M16, settlement uses M15. Deterministic, replayable, auditable, backward-compatible.
"""

from aurelius.research.instruments import (
    collateral,
    contracts,
    diagnostics,
    exercise,
    expiry,
    instrument,
    margin,
    pricing,
    reconciliation,
    risk,
    serialization,
    settlement,
    validation,
    valuation,
)
from aurelius.research.instruments.equity import equity
from aurelius.research.instruments.fixed_income import (
    bond,
    coupon_cash_flows,
    coupon_schedule,
)
from aurelius.research.instruments.forwards import forward, fx_forward
from aurelius.research.instruments.futures import future, roll
from aurelius.research.instruments.lifecycle import InstrumentBook
from aurelius.research.instruments.models import (
    CashConvention,
    CollateralBalance,
    ExerciseStatus,
    ExerciseStyle,
    Greeks,
    Instrument,
    InstrumentEvent,
    InstrumentEventType,
    InstrumentPosition,
    InstrumentType,
    MarginRequirement,
    OptionRight,
    SettlementStyle,
)
from aurelius.research.instruments.options import call, option, put
from aurelius.research.instruments.pricing import (
    BlackScholesPricer,
    DeterministicMockPricer,
    MockYieldProvider,
)
from aurelius.research.instruments.positions import DerivativePosition
from aurelius.research.instruments.registry import InstrumentRegistry
from aurelius.research.instruments.risk import InstrumentRiskReport, exposures
from aurelius.research.instruments.swaps import (
    CashFlow,
    PaymentSchedule,
    SwapLeg,
    interest_rate_swap,
    swap,
)
from aurelius.research.instruments.valuation import ValuationResult, value_position

__all__ = [
    "InstrumentBook", "InstrumentRegistry", "Instrument", "InstrumentType",
    "InstrumentPosition", "DerivativePosition", "CashConvention", "OptionRight",
    "ExerciseStyle", "ExerciseStatus", "SettlementStyle", "Greeks", "MarginRequirement",
    "CollateralBalance", "InstrumentEvent", "InstrumentEventType",
    "equity", "future", "roll", "option", "call", "put", "forward", "fx_forward",
    "swap", "interest_rate_swap", "SwapLeg", "PaymentSchedule", "CashFlow",
    "bond", "coupon_schedule", "coupon_cash_flows",
    "BlackScholesPricer", "DeterministicMockPricer", "MockYieldProvider",
    "value_position", "ValuationResult", "exposures", "InstrumentRiskReport",
    "instrument", "contracts", "pricing", "valuation", "margin", "collateral",
    "exercise", "expiry", "settlement", "reconciliation", "risk", "serialization",
    "validation", "diagnostics",
]
