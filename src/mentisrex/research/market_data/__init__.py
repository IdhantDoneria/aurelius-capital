"""AIDP M19 — Institutional Market Data, Curve Calibration & Volatility Surface Engine.

The layer *underneath* M18 valuation: it turns raw market sources into the immutable,
PIT-validated `MarketDataSnapshot` that M18 consumes. Sources → normalization → quality → PIT →
canonical observations → curve/vol calibration → snapshot. Reuses M18 curves/surfaces/snapshot,
M16 FX, M15 serialization; never duplicates the valuation, FX or risk engines.

    from mentisrex.research import market_data as md
    eng = md.MarketDataEngine(fx_provider=fx)
    result = eng.pipeline(as_of=d, raw=records, curve_instruments=insts, smiles=smiles)
    snapshot = result.snapshot            # an M18 MarketDataSnapshot, ready for the valuation engine
"""

from __future__ import annotations

from mentisrex.research.market_data.adapters import (
    BloombergAdapter,
    BrokerFeedAdapter,
    ExchangeFeedAdapter,
    RefinitivAdapter,
    VendorAdapter,
)
from mentisrex.research.market_data.bootstrap import (
    BootstrapResult,
    CurveBootstrapError,
    CurveBootstrapper,
)
from mentisrex.research.market_data.calendars import (
    BusinessCalendar,
    HolidayCalendar,
    JointCalendar,
    RollConvention,
    WeekendCalendar,
    calendar,
    india_calendar,
    uk_calendar,
    us_calendar,
)
from mentisrex.research.market_data.credit import (
    CDSQuote,
    CreditCurve,
    bootstrap_credit,
)
from mentisrex.research.market_data.engine import MarketDataEngine
from mentisrex.research.market_data.fixings import Fixing, FixingStore, FixingType
from mentisrex.research.market_data.identifiers import (
    IdentifierMap,
    IdentifierRecord,
    IdType,
)
from mentisrex.research.market_data.models import (
    CanonicalObservation,
    ObservationType,
    QualityDiagnostic,
    QualityStatus,
    Severity,
    Unit,
)
from mentisrex.research.market_data.multicurve import (
    MultiCurveSet,
    ois_multicurve,
    single_curve,
)
from mentisrex.research.market_data.normalization import (
    NormalizationResult,
    Normalizer,
)
from mentisrex.research.market_data.pit import (
    BuildResult,
    MarketDataSnapshotBuilder,
    PITPolicy,
    SnapshotBuildError,
)
from mentisrex.research.market_data.quality import (
    MarketDataQualityEngine,
    QualityConfig,
    QualityReport,
)
from mentisrex.research.market_data.rate_instruments import (
    InstrumentKind,
    RateConvention,
    RateInstrument,
    deposit,
    fra,
    ois,
    rate_future,
    swap,
)
from mentisrex.research.market_data.registry import (
    ComponentInfo,
    ComponentKind,
    MarketDataRegistry,
    default_market_data_registry,
)
from mentisrex.research.market_data.revisions import RevisionRecord, RevisionStore
from mentisrex.research.market_data.sabr import (
    SABRCalibration,
    SABRParams,
    calibrate_sabr,
    sabr_vol,
)
from mentisrex.research.market_data.sources import (
    DeterministicMockSource,
    HistoricalSource,
    MarketDataSource,
    StaticSource,
)
from mentisrex.research.market_data.svi import (
    SVICalibration,
    SVIParams,
    butterfly_arbitrage,
    calibrate_svi,
    durrleman_g,
)
from mentisrex.research.market_data.validation import (
    CalibrationValidator,
    CurveValidator,
    MarketDataValidator,
    SnapshotValidator,
    VolatilitySurfaceValidator,
)
from mentisrex.research.market_data.vol_calibration import (
    CalibratedVolProvider,
    SmileQuotes,
    SurfaceCalibrationReport,
    VolatilitySurfaceCalibrator,
    VolModel,
)

__version__ = "1.0.0"

__all__ = [
    "BloombergAdapter",
    "BootstrapResult",
    "BrokerFeedAdapter",
    "BuildResult",
    "BusinessCalendar",
    "CDSQuote",
    "CalibratedVolProvider",
    "CalibrationValidator",
    # models
    "CanonicalObservation",
    "ComponentInfo",
    "ComponentKind",
    "CreditCurve",
    "CurveBootstrapError",
    "CurveBootstrapper",
    "CurveValidator",
    "DeterministicMockSource",
    "ExchangeFeedAdapter",
    "Fixing",
    "FixingStore",
    "FixingType",
    "HistoricalSource",
    "HolidayCalendar",
    "IdType",
    # identifiers / calendars / revisions / fixings
    "IdentifierMap",
    "IdentifierRecord",
    "InstrumentKind",
    "JointCalendar",
    "MarketDataEngine",
    "MarketDataQualityEngine",
    "MarketDataRegistry",
    "MarketDataSnapshotBuilder",
    # sources / pipeline
    "MarketDataSource",
    # validation / registry / adapters
    "MarketDataValidator",
    "MultiCurveSet",
    "NormalizationResult",
    "Normalizer",
    "ObservationType",
    "PITPolicy",
    "QualityConfig",
    "QualityDiagnostic",
    "QualityReport",
    "QualityStatus",
    "RateConvention",
    # curves
    "RateInstrument",
    "RefinitivAdapter",
    "RevisionRecord",
    "RevisionStore",
    "RollConvention",
    "SABRCalibration",
    "SABRParams",
    "SVICalibration",
    "SVIParams",
    "Severity",
    "SmileQuotes",
    "SnapshotBuildError",
    "SnapshotValidator",
    "StaticSource",
    "SurfaceCalibrationReport",
    "Unit",
    "VendorAdapter",
    "VolModel",
    "VolatilitySurfaceCalibrator",
    "VolatilitySurfaceValidator",
    "WeekendCalendar",
    "bootstrap_credit",
    "butterfly_arbitrage",
    "calendar",
    "calibrate_sabr",
    "calibrate_svi",
    "default_market_data_registry",
    "deposit",
    "durrleman_g",
    "fra",
    "india_calendar",
    "ois",
    "ois_multicurve",
    "rate_future",
    # vol
    "sabr_vol",
    "single_curve",
    "swap",
    "uk_calendar",
    "us_calendar",
]
