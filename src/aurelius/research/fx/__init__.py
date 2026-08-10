"""Multi-Currency & FX Portfolio Book (AIDP M16).

Removes the single-currency assumption from the post-trade stack without forking M11
accounting. A `MultiCurrencyBook` holds one reused M15 `PostTradeEngine` per currency
(each a single-currency book of record) and adds only the FX overlay: dependency-injected
rate providers, explicit auditable conversions, multi-currency cash/settlement, base-
currency valuation, FX exposure / P&L / risk / stress, and currency-aware reconciliation,
reporting, tax and registry. Additive, deterministic, PIT-safe, replayable, and
backward-compatible: a single-currency book delegates straight through to M15.
"""

from aurelius.research.fx.accounting import (
    base_realized_pnl,
    base_unrealized_pnl,
    position_accounting,
)
from aurelius.research.fx.book import MultiCurrencyBook
from aurelius.research.fx.conversion import (
    conversion_from_dict,
    conversion_to_dict,
    convert,
    convert_to_target,
    round_trip_error,
)
from aurelius.research.fx.corporate_actions import apply as apply_corporate_action
from aurelius.research.fx.currency import (
    CurrencyMismatchError,
    is_valid_code,
    normalize,
    require_same,
    same_currency,
    validate_code,
)
from aurelius.research.fx.diagnostics import diagnostics, fingerprint
from aurelius.research.fx.exposure import fx_exposure
from aurelius.research.fx.hedging import (
    make_forward,
    make_future,
    make_swap,
    unhedged_by_currency,
)
from aurelius.research.fx.models import (
    CashByCurrencyReport,
    ConversionDirection,
    Currency,
    CurrencyAttributionReport,
    CurrencyBalance,
    CurrencyPair,
    CurrencyReconciliation,
    CurrencyRole,
    CurrencyValuation,
    FXConversion,
    FXDiagnostics,
    FXExposure,
    FXExposureReport,
    FXHedge,
    FXPnL,
    FXPnLReport,
    FXRate,
    FXRateSnapshot,
    FXReconciliationReport,
    FXRiskReport,
    FXStressResult,
    FXStressScenario,
    MultiCurrencyCash,
    MultiCurrencyPortfolioReport,
    MultiCurrencyPortfolioValue,
    SettlementCurrencyReport,
)
from aurelius.research.fx.performance import currency_attribution
from aurelius.research.fx.pnl import fx_pnl, value_snapshot
from aurelius.research.fx.rates import (
    DeterministicMockFXProvider,
    FXError,
    FXRateProvider,
    HistoricalFXRateProvider,
    InvalidFXRateError,
    MissingFXRateError,
    ProductionFXRateAdapter,
    StaleFXRateError,
    StaticFXRateProvider,
)
from aurelius.research.fx.reconciliation import reconcile
from aurelius.research.fx.registry import attach_fx
from aurelius.research.fx.reporting import (
    cash_by_currency_report,
    multi_currency_portfolio_report,
)
from aurelius.research.fx.risk import (
    CURRENCY_SCENARIOS,
    FXLimits,
    apply_fx_stress,
    check_fx_limits,
    fx_risk_report,
    stress_test,
)
from aurelius.research.fx.settlement_fx import (
    fund_settlement,
    obligations_by_currency,
    settlement_by_currency,
)
from aurelius.research.fx.validation import check_determinism, validate_book
from aurelius.research.fx.valuation import base_value, valuation

__all__ = [
    "CURRENCY_SCENARIOS",
    "CashByCurrencyReport",
    "ConversionDirection",
    "Currency",
    "CurrencyAttributionReport",
    "CurrencyBalance",
    "CurrencyMismatchError",
    "CurrencyPair",
    "CurrencyReconciliation",
    "CurrencyRole",
    "CurrencyValuation",
    "DeterministicMockFXProvider",
    "FXConversion",
    "FXDiagnostics",
    "FXError",
    "FXExposure",
    "FXExposureReport",
    "FXHedge",
    "FXLimits",
    "FXPnL",
    "FXPnLReport",
    "FXRate",
    "FXRateProvider",
    "FXRateSnapshot",
    "FXReconciliationReport",
    "FXRiskReport",
    "FXStressResult",
    "FXStressScenario",
    "HistoricalFXRateProvider",
    "InvalidFXRateError",
    "MissingFXRateError",
    "MultiCurrencyBook",
    "MultiCurrencyCash",
    "MultiCurrencyPortfolioReport",
    "MultiCurrencyPortfolioValue",
    "ProductionFXRateAdapter",
    "SettlementCurrencyReport",
    "StaleFXRateError",
    "StaticFXRateProvider",
    "apply_corporate_action",
    "apply_fx_stress",
    "attach_fx",
    "base_realized_pnl",
    "base_unrealized_pnl",
    "base_value",
    "cash_by_currency_report",
    "check_determinism",
    "check_fx_limits",
    "conversion_from_dict",
    "conversion_to_dict",
    "convert",
    "convert_to_target",
    "currency_attribution",
    "diagnostics",
    "fingerprint",
    "fund_settlement",
    "fx_exposure",
    "fx_pnl",
    "fx_risk_report",
    "is_valid_code",
    "make_forward",
    "make_future",
    "make_swap",
    "multi_currency_portfolio_report",
    "normalize",
    "obligations_by_currency",
    "position_accounting",
    "reconcile",
    "require_same",
    "round_trip_error",
    "same_currency",
    "settlement_by_currency",
    "stress_test",
    "unhedged_by_currency",
    "validate_book",
    "validate_code",
    "valuation",
    "value_snapshot",
]
