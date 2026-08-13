"""M21 open-data provider package (AIDP M21).

Registers every free/public-data source adapter against the M20 operational registry.
Each adapter is a production contract: conversion logic (vendor record → SourceMessage) is
fully implemented offline; the actual network fetch raises NotImplementedError — subclass and
wire the transport for a live deployment.

ProviderMetadata carries governance fields: name, version, license, coverage, datasets,
limitations, and a stable content fingerprint for audit lineage.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from mentisrex.research.market_data.registry import ComponentInfo, ComponentKind
from mentisrex.research.market_data_ops.registry import default_ops_registry


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    version: str
    license: str
    coverage: str                  # geographic / asset-class scope
    datasets: tuple                # e.g. ("ohlcv", "fundamentals", "macro")
    limitations: tuple             # e.g. ("delayed_15min", "no_tick", "rate_limited")
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            fp = hashlib.blake2b(
                f"{self.name}|{self.version}".encode(), digest_size=8
            ).hexdigest()
            object.__setattr__(self, "fingerprint", fp)


# ── canonical M21 provider catalogue ─────────────────────────────────────────

OPENBB = ProviderMetadata(
    name="openbb", version="1.0.0",
    license="MIT (OpenBB SDK); underlying data sources vary",
    coverage="global equities, ETFs, FX, macro (FRED/IMF/WorldBank/ECB)",
    datasets=("ohlcv", "company_info", "fundamentals", "fx_rate", "macro"),
    limitations=("requires_openbb_install", "rate_limited_per_source",
                 "coverage_varies_by_backend"),
)

FINCEPT = ProviderMetadata(
    name="fincept", version="1.0.0",
    license="Apache-2.0 (connector); underlying data sources vary",
    coverage="global — Yahoo Finance, SEC/EDGAR, FRED, IMF, World Bank, data.gov.in, NSE",
    datasets=("ohlcv", "fundamentals", "macro", "india_equities"),
    limitations=("requires_fincept_install", "rate_limited", "no_tick_data"),
)

YAHOO = ProviderMetadata(
    name="yahoo_finance", version="1.0.0",
    license="Data: Yahoo Finance ToS (non-commercial); yfinance: Apache-2.0",
    coverage="global equities, ETFs, FX, crypto, indices",
    datasets=("ohlcv", "adjusted_close", "dividends", "splits", "corporate_actions"),
    limitations=("15min_delay", "partial_corporate_actions", "ticker_reuse_risk",
                 "no_commercial_use"),
)

SEC_EDGAR = ProviderMetadata(
    name="sec_edgar", version="1.0.0",
    license="Public domain (SEC EDGAR data)",
    coverage="US public companies — XBRL-tagged financial statements",
    datasets=("balance_sheet", "income_statement", "cash_flow",
              "company_facts", "filings_metadata"),
    limitations=("us_only", "xbrl_tagged_filings_only", "no_realtime",
                 "restatement_detection_approximate"),
)

FRED = ProviderMetadata(
    name="fred", version="1.0.0",
    license="Public domain (Federal Reserve Bank of St. Louis)",
    coverage="US macro — GDP, CPI, unemployment, rates, monetary indicators",
    datasets=("gdp", "inflation", "unemployment", "interest_rates", "monetary"),
    limitations=("us_focused", "optional_api_key_for_higher_limits",
                 "bitemporal_revision_available"),
)

INDIA = ProviderMetadata(
    name="india", version="1.0.0",
    license="NSE: free for personal use; BSE: free for personal use; data.gov.in: NOGI",
    coverage="India — NSE/BSE equities, corporate actions, macro",
    datasets=("nse_ohlcv", "bse_ohlcv", "corporate_actions", "india_macro"),
    limitations=("limited_history", "isin_required_for_dedup",
                 "data_gov_in_irregular_updates"),
)

QLIB = ProviderMetadata(
    name="qlib_compat", version="1.0.0",
    license="MIT (qlib); Mentisrex data: internal",
    coverage="Mentisrex datasets exported in Qlib-compatible format",
    datasets=("ohlcv_export", "factor_datasets", "label_datasets"),
    limitations=("export_only", "no_qlib_portfolio_engine",
                 "no_qlib_execution_logic"),
)

FINANCETOOLKIT = ProviderMetadata(
    name="financetoolkit", version="1.0.0",
    license="MIT (FinanceToolkit-style ratios; no FinanceToolkit library required)",
    coverage="Fundamental analytics derived from CanonicalObservation inputs",
    datasets=("profitability_ratios", "margin_ratios",
              "valuation_multiples", "financial_ratios"),
    limitations=("derived_not_raw", "depends_on_sec_edgar_observations",
                 "no_replace_m11_accounting", "no_replace_m13_risk",
                 "no_replace_m18_valuation"),
)

ALL_PROVIDERS = (OPENBB, FINCEPT, YAHOO, SEC_EDGAR, FRED, INDIA, QLIB, FINANCETOOLKIT)


def default_m21_registry():
    """M20 registry extended with M21 open-data provider components."""
    r = default_ops_registry()
    for meta in ALL_PROVIDERS:
        r.register(ComponentInfo(
            ComponentKind.PROVIDER,
            f"m21.{meta.name}",
            meta.version,
            f"M21 open-data adapter: {meta.coverage}",
        ))
    return r
