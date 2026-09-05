"""Stress testing (AIDP M13).

Applies deterministic shock scenarios to a portfolio and reports the P&L. Ships a
library of historical scenarios (2008 GFC, 2020 COVID, 2022 inflation shock) and
accepts custom `StressScenario`s. Shocks supported: portfolio/market return,
per-sector return (needs a sector map), volatility multiplier (reported), and
liquidity reduction (feeds the liquidity engine). Pure — no market data required.
"""

from __future__ import annotations

from mentisrex.research.risk.models import StressResult, StressScenario, StressTestReport

# Canonical historical scenarios (approximate peak-to-trough equity shocks).
HISTORICAL_SCENARIOS = {
    "gfc_2008": StressScenario(
        "gfc_2008", market_shock=-0.50, vol_multiplier=2.5, liquidity_multiplier=0.4
    ),
    "covid_2020": StressScenario(
        "covid_2020", market_shock=-0.34, vol_multiplier=3.0, liquidity_multiplier=0.5
    ),
    "inflation_2022": StressScenario(
        "inflation_2022", market_shock=-0.25, vol_multiplier=1.6, liquidity_multiplier=0.7
    ),
}


def apply_scenario(
    weights: dict,
    scenario: StressScenario,
    *,
    value: float = 1.0,
    sectors: dict | None = None,
    betas: dict | None = None,
    halt_threshold: float = -0.20,
) -> StressResult:
    """P&L fraction = Σ w_i · shock_i. Shock per name = market_shock·beta (beta=1 if
    none) + its sector shock. Gross-weighted so shorts gain in a sell-off."""
    pnl = 0.0
    for sid, w in (weights or {}).items():
        beta = (betas or {}).get(sid, 1.0)
        shock = scenario.market_shock * beta
        if sectors and scenario.sector_shocks:
            shock += scenario.sector_shocks.get(sectors.get(sid), 0.0)
        pnl += w * shock
    return StressResult(
        scenario=scenario.name,
        pnl_fraction=float(pnl),
        stressed_value=float(value * (1 + pnl)),
        breached=bool(pnl <= halt_threshold),
    )


def stress_test(
    weights: dict,
    *,
    scenarios=None,
    value: float = 1.0,
    sectors=None,
    betas=None,
    halt_threshold: float = -0.20,
) -> StressTestReport:
    scen = scenarios if scenarios is not None else list(HISTORICAL_SCENARIOS.values())
    results = [
        apply_scenario(
            weights, s, value=value, sectors=sectors, betas=betas, halt_threshold=halt_threshold
        )
        for s in scen
    ]
    worst = min(results, key=lambda r: r.pnl_fraction, default=None)
    return StressTestReport(
        results=results,
        worst_scenario=worst.scenario if worst else "none",
        worst_pnl_fraction=worst.pnl_fraction if worst else 0.0,
    )
