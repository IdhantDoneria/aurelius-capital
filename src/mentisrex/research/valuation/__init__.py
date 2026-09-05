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

from mentisrex.research.valuation import (
    adapters,
    american,
    bonds,
    cross_currency,
    curves,
    daycount,
    diagnostics,
    futures,
    fx,
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
from mentisrex.research.valuation.adapters import M18Pricer, M18YieldProvider
from mentisrex.research.valuation.bonds import BondSpec
from mentisrex.research.valuation.curves import (
    DiscountCurve,
    ForwardCurve,
    ZeroCurve,
    flat_curve,
)
from mentisrex.research.valuation.daycount import Compounding, DayCount
from mentisrex.research.valuation.engine import (
    PortfolioValuationEngine,
    ValuationEngine,
    ValuationError,
)
from mentisrex.research.valuation.models import (
    Greeks,
    MarketDataSnapshot,
    MarketQuote,
    PortfolioValuation,
    Provenance,
    ValuationConfiguration,
    ValuationResult,
)
from mentisrex.research.valuation.providers import (
    DeterministicMockMarketDataProvider,
    HistoricalMarketDataProvider,
    MarketDataProvider,
    ProductionMarketDataAdapter,
    StaticMarketDataProvider,
)
from mentisrex.research.valuation.registry import (
    CurveBuilder,
    CurveCalibrationReport,
    ModelInfo,
    ModelRegistry,
    default_registry,
)
from mentisrex.research.valuation.snapshot import build_snapshot, is_pit_safe, validate_pit
from mentisrex.research.valuation.swaps import SwapSpec
from mentisrex.research.valuation.validation import ValuationValidator
from mentisrex.research.valuation.volatility import (
    ConstantVolProvider,
    SurfaceVolProvider,
    VolatilitySurface,
    flat_surface,
)

__all__ = [
    # analytics specs
    "BondSpec",
    "Compounding",
    "ConstantVolProvider",
    "CurveBuilder",
    "CurveCalibrationReport",
    "DayCount",
    "DeterministicMockMarketDataProvider",
    "DiscountCurve",
    "ForwardCurve",
    "Greeks",
    "HistoricalMarketDataProvider",
    # M17 adapters
    "M18Pricer",
    "M18YieldProvider",
    "MarketDataProvider",
    "MarketDataSnapshot",
    "MarketQuote",
    "ModelInfo",
    # governance
    "ModelRegistry",
    "PortfolioValuation",
    "PortfolioValuationEngine",
    "ProductionMarketDataAdapter",
    "Provenance",
    "StaticMarketDataProvider",
    "SurfaceVolProvider",
    "SwapSpec",
    "ValuationConfiguration",
    # engine + results
    "ValuationEngine",
    "ValuationError",
    "ValuationResult",
    "ValuationValidator",
    "VolatilitySurface",
    # curves + vol
    "ZeroCurve",
    "adapters",
    "american",
    "bonds",
    # market data
    "build_snapshot",
    "cross_currency",
    "curves",
    "daycount",
    "default_registry",
    "diagnostics",
    "engine",
    "flat_curve",
    "flat_surface",
    "futures",
    "fx",
    "greeks",
    "interpolation",
    "is_pit_safe",
    # submodules
    "pricing",
    "providers",
    "reconciliation",
    "serialization",
    "snapshot",
    "swaps",
    "validate_pit",
    "validation",
    "volatility",
]
