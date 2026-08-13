"""Import all models so Alembic autogenerate sees them all."""

from mentisrex.infrastructure.database.models.base import Base
from mentisrex.infrastructure.database.models.fundamental import (
    EarningsEvent,
    FinancialRatios,
    FinancialStatement,
)
from mentisrex.infrastructure.database.models.market import (
    CorporateAction,
    MarketDataOHLCV,
    MarketDataQuote,
    MarketDataTick,
    OrderBookSnapshot,
)
from mentisrex.infrastructure.database.models.reference import DataSource, Exchange, Symbol
from mentisrex.infrastructure.database.models.research import (
    ExperimentMetric,
    ExperimentRun,
    FeatureDefinition,
    FeatureValue,
    ModelRegistry,
    SignalPrediction,
)
from mentisrex.infrastructure.database.models.trading import (
    Account,
    Fill,
    Order,
    PnLSnapshot,
    Position,
    RiskEvent,
    Strategy,
)

__all__ = [
    "Account",
    "Base",
    "CorporateAction",
    "DataSource",
    "EarningsEvent",
    "Exchange",
    "ExperimentMetric",
    "ExperimentRun",
    "FeatureDefinition",
    "FeatureValue",
    "Fill",
    "FinancialRatios",
    "FinancialStatement",
    "MarketDataOHLCV",
    "MarketDataQuote",
    "MarketDataTick",
    "ModelRegistry",
    "Order",
    "OrderBookSnapshot",
    "PnLSnapshot",
    "Position",
    "RiskEvent",
    "SignalPrediction",
    "Strategy",
    "Symbol",
]
