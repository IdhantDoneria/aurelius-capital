"""Currency performance attribution (AIDP M16).

Extends M15 performance to the currency dimension: decomposes the base-currency return
over a marking period into local-asset, FX (translation) and interaction return using
the exact `fx_pnl` identity, so the attribution always reconciles to the total.
"""

from __future__ import annotations

from mentisrex.research.fx.models import CurrencyAttributionReport
from mentisrex.research.fx.pnl import fx_pnl


def currency_attribution(book, snap0: dict, snap1: dict) -> CurrencyAttributionReport:
    rep = fx_pnl(book, snap0, snap1)
    base0 = sum(v * r for v, r in snap0.values()) or 1.0
    return CurrencyAttributionReport(
        base_currency=book.base_currency,
        local_return=rep.local_pnl / base0, fx_return=rep.fx_pnl / base0,
        interaction=rep.interaction / base0, total_return=rep.total_pnl / base0,
        by_currency={c: p.total_base / base0 for c, p in rep.by_currency.items()},
        reconciles=rep.reconciles)
