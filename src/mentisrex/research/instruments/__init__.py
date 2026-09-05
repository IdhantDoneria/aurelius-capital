"""Multi-Asset & Derivatives Accounting Engine (AIDP M17).

A general instrument framework layered additively over M11–M16. Equities delegate straight
to the reused M15 `PostTradeEngine` (byte-identical behaviour); futures, options, forwards,
swaps and bonds get a derivative overlay — contract-aware positions, margin, collateral,
mark-to-market, expiry/exercise/assignment — while every cash flow still runs through the
single M11 ledger. Pricing, Greeks and yields are dependency-injected; risk feeds M13, FX
uses M16, settlement uses M15. Deterministic, replayable, auditable, backward-compatible.
"""

from mentisrex.research.instruments import (
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
from mentisrex.research.instruments.equity import equity
from mentisrex.research.instruments.fixed_income import (
    bond,
    coupon_cash_flows,
    coupon_schedule,
)
from mentisrex.research.instruments.forwards import forward, fx_forward
from mentisrex.research.instruments.futures import future, roll
from mentisrex.research.instruments.lifecycle import InstrumentBook
from mentisrex.research.instruments.models import (
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
from mentisrex.research.instruments.options import call, option, put
from mentisrex.research.instruments.positions import DerivativePosition
from mentisrex.research.instruments.pricing import (
    BlackScholesPricer,
    DeterministicMockPricer,
    MockYieldProvider,
)
from mentisrex.research.instruments.registry import InstrumentRegistry
from mentisrex.research.instruments.risk import InstrumentRiskReport, exposures
from mentisrex.research.instruments.swaps import (
    CashFlow,
    PaymentSchedule,
    SwapLeg,
    interest_rate_swap,
    swap,
)
from mentisrex.research.instruments.valuation import ValuationResult, value_position

__all__ = [
    "BlackScholesPricer",
    "CashConvention",
    "CashFlow",
    "CollateralBalance",
    "DerivativePosition",
    "DeterministicMockPricer",
    "ExerciseStatus",
    "ExerciseStyle",
    "Greeks",
    "Instrument",
    "InstrumentBook",
    "InstrumentEvent",
    "InstrumentEventType",
    "InstrumentPosition",
    "InstrumentRegistry",
    "InstrumentRiskReport",
    "InstrumentType",
    "MarginRequirement",
    "MockYieldProvider",
    "OptionRight",
    "PaymentSchedule",
    "SettlementStyle",
    "SwapLeg",
    "ValuationResult",
    "bond",
    "call",
    "collateral",
    "contracts",
    "coupon_cash_flows",
    "coupon_schedule",
    "diagnostics",
    "equity",
    "exercise",
    "expiry",
    "exposures",
    "forward",
    "future",
    "fx_forward",
    "instrument",
    "interest_rate_swap",
    "margin",
    "option",
    "pricing",
    "put",
    "reconciliation",
    "risk",
    "roll",
    "serialization",
    "settlement",
    "swap",
    "validation",
    "valuation",
    "value_position",
]
