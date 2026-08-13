"""Frozen StrategySpecification for the controlled forward paper-trading run.

EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED.

This module produces a single immutable StrategySpecification.  Import SPEC
anywhere; the configuration_fingerprint is stamped once at module load time.
Do NOT modify fields after import — any material change requires a new version,
new spec, new fingerprint, and a separately reviewed change.

Research lineage:
  research_artifact_id  : "SIM"   — simulation experiment used in M9 validation
  validation_artifact_id: "696a411bed6731a997c399584bfa9c4f"
                          M9 manifest_hash for the SIM experiment (overall_verdict=PASS,
                          confidence_score=88.1, Sharpe=2.12, n=729 obs)

Because the underlying experiment_id is labelled "SIM" (a validation-framework
test fixture, not a named production research campaign), the strategy is
classified EXPERIMENTAL_PAPER with validation_status=REQUIRES_REVIEW, and must
never be confused with a validated deployable strategy.
"""

from __future__ import annotations

from mentisrex.research.strategy_deployment.models import StrategyType, make_spec

# ── identifiers ───────────────────────────────────────────────────────────────
STRATEGY_ID = "ew-momentum-exp"
STRATEGY_VERSION = "1.0.0"

# ── research lineage (immutable references) ───────────────────────────────────
RESEARCH_ARTIFACT_ID = "SIM"
VALIDATION_ARTIFACT_ID = "696a411bed6731a997c399584bfa9c4f"
VALIDATION_STATUS = "REQUIRES_REVIEW"

# ── paper capital (not real money) ────────────────────────────────────────────
STARTING_CAPITAL = 1_000_000.0   # USD, paper only

# ── universe (fixed; any change requires new spec version) ───────────────────
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN",
    "META", "NVDA", "TSLA", "JPM", "JNJ", "V",
]

# ── frozen spec ───────────────────────────────────────────────────────────────
SPEC = make_spec(
    strategy_id=STRATEGY_ID,
    strategy_name="Equal-Weight Momentum (Experimental Paper)",
    version=STRATEGY_VERSION,
    description=(
        "EXPERIMENTAL PAPER TRADING — NOT PRODUCTION APPROVED. "
        "Equal-weight cross-sectional strategy for controlled forward observation. "
        "Signals equal 1.0 for each universe security with a positive price in the snapshot. "
        "Portfolio construction: equal_weight, long_only, max_position_weight=0.20."
    ),
    strategy_type=StrategyType.EXPERIMENTAL_PAPER,
    research_artifact_id=RESEARCH_ARTIFACT_ID,
    validation_artifact_id=VALIDATION_ARTIFACT_ID,
    validation_status=VALIDATION_STATUS,
    universe_definition={
        "type": "equity",
        "securities": UNIVERSE,
        "source": "fixed",
        "note": "Fixed universe for experimental forward observation run.",
    },
    required_data=["close", "price"],
    feature_definition={
        "type": "price_level",
        "lookback_days": 0,
        "note": "Reads current snapshot price only; no historical lookback.",
    },
    signal_definition={
        "type": "equal_weight",
        "universe": UNIVERSE,
        "rule": "signal=1.0 for each security with price>0 in snapshot",
    },
    rebalance_frequency="monthly",
    portfolio_construction_config={
        "objective": "equal_weight",
        "long_only": True,
        "max_position_weight": 0.20,
    },
    risk_config={
        "max_position": 0.20,
        "max_gross_leverage": 1.0,
        "long_only": True,
    },
    execution_config={
        "algo": "market",
        "direct_provider_access": False,  # strategy logic must not call providers
    },
    transaction_cost_assumption={
        "slippage_bps": 5.0,
        "commission_per_share": 0.005,
    },
    slippage_assumption={"model": "linear", "bps": 5.0},
    benchmark="SPY",
    base_currency="USD",
    allowed_instruments=["equity"],
    capital_assumption=STARTING_CAPITAL,
    model_version="1.0.0",
    dependency_versions={"mentisrex_milestone": "M24"},
)
