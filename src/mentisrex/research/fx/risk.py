"""FX risk & currency stress (AIDP M16).

Currency-dimension risk on top of M13 — it does not duplicate M13's covariance/VaR
engine; it injects per-currency vols and reuses the M13 idea (z·σ·exposure). Exposes FX
volatility contribution, currency concentration, a diagonal FX VaR (full cross-currency
covariance is an injected interface), FX limit checks that can warn/reject, and
deterministic currency stress scenarios (single or simultaneous multi-currency shocks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from mentisrex.research.fx.currency import validate_code
from mentisrex.research.fx.exposure import fx_exposure
from mentisrex.research.fx.models import FXRiskReport, FXStressResult, FXStressScenario
from mentisrex.research.fx.valuation import valuation

_Z = {0.90: 1.2816, 0.95: 1.6449, 0.975: 1.96, 0.99: 2.3263, 0.995: 2.5758}


def _z(confidence: float) -> float:
    return _Z.get(round(confidence, 3), 2.3263)


@dataclass
class FXLimits:
    max_currency_share: float = 1.0  # max |net exposure|/value per non-base ccy
    max_gross_fx: float = float("inf")  # max Σ|net|/value across currencies
    per_currency: dict = field(default_factory=dict)  # ccy -> max share override


def check_fx_limits(
    book, limits: FXLimits, *, as_of: date | None = None, prices: dict | None = None
) -> list:
    exp = fx_exposure(book, as_of=as_of, prices=prices)
    tv = valuation(book, as_of=as_of).total_base or 1.0
    violations: list = []
    if limits.max_gross_fx < float("inf") and exp.gross / tv > limits.max_gross_fx + 1e-12:
        violations.append(
            {"limit": "max_gross_fx", "value": exp.gross / tv, "cap": limits.max_gross_fx}
        )
    for ccy, e in exp.by_currency.items():
        cap = limits.per_currency.get(ccy, limits.max_currency_share)
        share = abs(e.net_base) / tv
        if share > cap + 1e-12:
            violations.append(
                {"limit": "max_currency_share", "currency": ccy, "value": share, "cap": cap}
            )
    return violations


def fx_risk_report(
    book,
    *,
    vols: dict | None = None,
    confidence: float = 0.99,
    as_of: date | None = None,
    prices: dict | None = None,
    limits: FXLimits | None = None,
) -> FXRiskReport:
    exp = fx_exposure(book, as_of=as_of, prices=prices)
    tv = valuation(book, as_of=as_of).total_base or 1.0
    vols = {validate_code(k): float(v) for k, v in (vols or {}).items()}
    z = _z(confidence)

    by: dict = {}
    var_sq = 0.0
    for ccy, e in exp.by_currency.items():
        vol = vols.get(ccy, 0.0)
        var_sq += (e.net_base * vol) ** 2
        by[ccy] = {
            "exposure_base": e.net_base,
            "share": e.net_base / tv,
            "vol": vol,
            "contribution": abs(e.net_base) * vol,
            "var": z * abs(e.net_base) * vol,
        }
    fx_var = z * (var_sq**0.5)  # diagonal (independent-currency) VaR
    violations = check_fx_limits(book, limits, as_of=as_of) if limits else []
    return FXRiskReport(
        base_currency=book.base_currency,
        by_currency=by,
        fx_var=fx_var,
        largest_currency=exp.largest_currency,
        concentration=exp.largest_share,
        violations=violations,
    )


# ── deterministic currency stress ─────────────────────────────────────────────

CURRENCY_SCENARIOS = {
    "usd_up_10": FXStressScenario("usd_up_10", {"USD": 0.10}),
    "usd_down_10": FXStressScenario("usd_down_10", {"USD": -0.10}),
    "eur_up_10": FXStressScenario("eur_up_10", {"EUR": 0.10}),
    "eur_down_10": FXStressScenario("eur_down_10", {"EUR": -0.10}),
    "inr_depreciation": FXStressScenario("inr_depreciation", {"INR": -0.15}),
    "jpy_appreciation": FXStressScenario("jpy_appreciation", {"JPY": 0.12}),
    "broad_usd_shock": FXStressScenario("broad_usd_shock", {"USD": 0.15}),
    "em_fx_shock": FXStressScenario("em_fx_shock", {"INR": -0.20, "BRL": -0.20, "ZAR": -0.20}),
}


def _effective_shock(scenario: FXStressScenario, ccy: str, base: str) -> float:
    """Move of `ccy`'s base value: its own shock minus the base currency's shock
    (base strengthening drags every foreign currency down by the same amount)."""
    if ccy == base:
        return 0.0
    shocks = {validate_code(k): v for k, v in scenario.shocks.items()}
    return shocks.get(ccy, 0.0) - shocks.get(base, 0.0)


def apply_fx_stress(
    book, scenario: FXStressScenario, *, as_of: date | None = None, prices: dict | None = None
) -> FXStressResult:
    val = valuation(book, as_of=as_of, prices=prices)
    base_val = val.total_base
    stressed = 0.0
    by: dict = {}
    for ccy, cv in val.by_currency.items():
        shock = _effective_shock(scenario, ccy, book.base_currency)
        new_base = cv.total_base * (1 + shock)
        by[ccy] = new_base - cv.total_base
        stressed += new_base
    return FXStressResult(
        scenario=scenario.name,
        base_value=base_val,
        stressed_base_value=stressed,
        pnl_base=stressed - base_val,
        pnl_fraction=(stressed - base_val) / base_val if base_val else 0.0,
        by_currency=by,
    )


def stress_test(
    book, *, scenarios=None, as_of: date | None = None, prices: dict | None = None
) -> list:
    scen = scenarios if scenarios is not None else list(CURRENCY_SCENARIOS.values())
    return [apply_fx_stress(book, s, as_of=as_of, prices=prices) for s in scen]
