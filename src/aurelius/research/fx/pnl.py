"""FX P&L decomposition (AIDP M16).

Splits the base-currency change of each currency bucket over a marking period into
local, FX (translation) and interaction effects using the exact identity

    Δ(V·R) = R0·ΔV  +  V0·ΔR  +  ΔV·ΔR
             local     fx          interaction

which sums to the true base-value change by construction — the decomposition always
reconciles. Inputs are two `value_snapshot`s (local value + base rate per currency).
Realized FX P&L (from explicit conversions) is carried at the report level from the
book; trade/mark-driven translation shows up as the FX/unrealized term.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.fx.models import FXPnL, FXPnLReport
from aurelius.research.fx.valuation import valuation


def value_snapshot(book, *, as_of: date | None = None, prices: dict | None = None) -> dict:
    """{ccy: (local_value, base_rate)} at `as_of` — the input to `fx_pnl`."""
    val = valuation(book, as_of=as_of, prices=prices)
    return {c: (cv.total_local, cv.fx_rate_to_base) for c, cv in val.by_currency.items()}


def fx_pnl(book, snap0: dict, snap1: dict, *, tol: float = 1e-6) -> FXPnLReport:
    by: dict = {}
    local_t = fx_t = inter_t = 0.0
    for ccy in sorted(set(snap0) | set(snap1)):
        s0, s1 = snap0.get(ccy), snap1.get(ccy)
        v0, r0 = s0 if s0 else (0.0, s1[1] if s1 else 1.0)
        v1, r1 = s1 if s1 else (0.0, s0[1] if s0 else 1.0)
        dv, dr = v1 - v0, r1 - r0
        local, fxp, inter = r0 * dv, v0 * dr, dv * dr
        by[ccy] = FXPnL(currency=ccy, local_pnl_base=local, fx_pnl_base=fxp,
                        interaction_base=inter, total_base=local + fxp + inter,
                        realized_fx_base=0.0, unrealized_fx_base=fxp)
        local_t += local
        fx_t += fxp
        inter_t += inter

    total = local_t + fx_t + inter_t
    base0 = sum(v * r for v, r in snap0.values())
    base1 = sum(v * r for v, r in snap1.values())
    reconciles = abs(total - (base1 - base0)) <= max(tol, abs(base1) * 1e-9)
    return FXPnLReport(
        base_currency=book.base_currency, by_currency=by, local_pnl=local_t, fx_pnl=fx_t,
        interaction=inter_t, total_pnl=total, realized_fx=book.realized_fx_pnl,
        unrealized_fx=fx_t, reconciles=reconciles)
