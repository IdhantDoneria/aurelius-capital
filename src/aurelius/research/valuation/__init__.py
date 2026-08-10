"""Institutional Valuation & Market-Data Infrastructure (AIDP M18).

One canonical, deterministic, point-in-time valuation architecture for every asset class in
the platform. Core rule: a valuation is reproducible from Instrument + MarketDataSnapshot +
ValuationDate + ValuationConfiguration, and the engine NEVER silently fetches live data —
market data is injected as an immutable, provenance-stamped snapshot.

Supplies price / NPV / Greeks / yield / duration / DV01 / FX exposure to M10-M17. Reuses M16
FX (`FXRateProvider`) and the M17 instrument model; feeds M13 risk (which stays the risk
authority). Production Black-Scholes / Black-76 / binomial-American pricing, curve & vol-surface
infrastructure, bond & swap analytics, cross-currency valuation, model governance and
arbitrage diagnostics.
"""

from aurelius.research.valuation import (
    adapters,
    american,
    bonds,
    cross_currency,
    curves,
    daycount,
    diagnostics,
    fx,
    futures,
    greeks,
    interpolation,
    pricing,
    providers,
    reconciliation,
    serialization,
    snapshot,
    swaps,
    validation,
    volatility,
)
from aurelius.research.valuation.adapters import M18Pricer, M18YieldProvider
from aurelius.research.valuation.bonds import BondSpec
from aurelius.research.valuation.curves import (
    DiscountCurve,
    ForwardCurve,
    ZeroCurve,
    flat_curve,
)
from aurelius.research.valuation.daycount import Compounding, DayCount
from aurelius.research.valuation.engine import (
    PortfolioValuationEngine,
    ValuationEngine,
    ValuationError,
)
from aurelius.research.valuation.models import (
    Greeks,
    MarketDataSnapshot,
    MarketQuote,
    PortfolioValuation,
    Provenance,
    ValuationConfiguration,
    ValuationResult,
)
from aurelius.research.valuation.providers import (
    DeterministicMockMarketDataProvider,
    HistoricalMarketDataProvider,
    MarketDataProvider,
    ProductionMarketDataAdapter,
    StaticMarketDataProvider,
)
from aurelius.research.valuation.registry import (
    CurveBuilder,
    CurveCalibrationReport,
    ModelInfo,
    ModelRegistry,
    default_registry,
)
from aurelius.research.valuation.snapshot import build_snapshot, is_pit_safe, validate_pit
from aurelius.research.valuation.swaps import SwapSpec
from aurelius.research.valuation.validation import ValuationValidator
from aurelius.research.valuation.volatility import (
    ConstantVolProvider,
    SurfaceVolProvider,
    VolatilitySurface,
    flat_surface,
)

__all__ = [
    # engine + results
    "ValuationEngine", "PortfolioValuationEngine", "ValuationError",
    "ValuationResult", "PortfolioValuation", "ValuationConfiguration",
    "MarketDataSnapshot", "MarketQuote", "Provenance", "Greeks",
    # market data
    "build_snapshot", "validate_pit", "is_pit_safe",
    "MarketDataProvider", "StaticMarketDataProvider", "HistoricalMarketDataProvider",
    "DeterministicMockMarketDataProvider", "ProductionMarketDataAdapter",
    # curves + vol
    "ZeroCurve", "DiscountCurve", "ForwardCurve", "flat_curve",
    "VolatilitySurface", "flat_surface", "ConstantVolProvider", "SurfaceVolProvider",
    "DayCount", "Compounding",
    # analytics specs
    "BondSpec", "SwapSpec",
    # governance
    "ModelRegistry", "ModelInfo", "default_registry", "CurveBuilder",
    "CurveCalibrationReport", "ValuationValidator",
    # M17 adapters
    "M18Pricer", "M18YieldProvider",
    # submodules
    "pricing", "american", "bonds", "swaps", "futures", "fx", "cross_currency",
    "curves", "volatility", "interpolation", "daycount", "providers", "engine",
    "greeks", "adapters", "validation", "diagnostics", "reconciliation",
    "serialization", "snapshot",
]
