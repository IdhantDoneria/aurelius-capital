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
    CurveBootstrapper,
    CurveBootstrapError,
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
    "MarketDataEngine",
    # models
    "CanonicalObservation", "ObservationType", "Unit", "QualityStatus", "Severity",
    "QualityDiagnostic",
    # identifiers / calendars / revisions / fixings
    "IdentifierMap", "IdentifierRecord", "IdType",
    "BusinessCalendar", "WeekendCalendar", "HolidayCalendar", "JointCalendar", "RollConvention",
    "calendar", "us_calendar", "uk_calendar", "india_calendar",
    "RevisionStore", "RevisionRecord", "FixingStore", "Fixing", "FixingType",
    # sources / pipeline
    "MarketDataSource", "StaticSource", "HistoricalSource", "DeterministicMockSource",
    "Normalizer", "NormalizationResult",
    "MarketDataQualityEngine", "QualityConfig", "QualityReport",
    "MarketDataSnapshotBuilder", "BuildResult", "PITPolicy", "SnapshotBuildError",
    # curves
    "RateInstrument", "RateConvention", "InstrumentKind",
    "deposit", "ois", "fra", "rate_future", "swap",
    "CurveBootstrapper", "BootstrapResult", "CurveBootstrapError",
    "MultiCurveSet", "single_curve", "ois_multicurve",
    "CreditCurve", "CDSQuote", "bootstrap_credit",
    # vol
    "sabr_vol", "SABRParams", "SABRCalibration", "calibrate_sabr",
    "SVIParams", "SVICalibration", "calibrate_svi", "durrleman_g", "butterfly_arbitrage",
    "VolatilitySurfaceCalibrator", "VolModel", "SmileQuotes", "SurfaceCalibrationReport",
    "CalibratedVolProvider",
    # validation / registry / adapters
    "MarketDataValidator", "CurveValidator", "CalibrationValidator",
    "VolatilitySurfaceValidator", "SnapshotValidator",
    "MarketDataRegistry", "ComponentInfo", "ComponentKind", "default_market_data_registry",
    "VendorAdapter", "BloombergAdapter", "RefinitivAdapter", "ExchangeFeedAdapter",
    "BrokerFeedAdapter",
]
