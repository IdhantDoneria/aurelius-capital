"""FX hedging interface (AIDP M16).

NOT an FX trading strategy — an interface for future hedge infrastructure. A hedge is
represented abstractly as an `FXHedge` carrying a base-currency notional that offsets
exposure in a currency; `fx_exposure` already nets hedges out. Forward / future / swap
constructors record the instrument type and (optional) rate/maturity but are not priced
or settled in M16. Unblock: add a pricing/settlement engine that turns these into cash
flows and mark-to-market P&L.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.fx.currency import validate_code
from aurelius.research.fx.exposure import fx_exposure
from aurelius.research.fx.models import FXHedge

_seq = {"n": 0}


def _next_id() -> str:
    _seq["n"] += 1
    return f"H{_seq['n']:06d}"


def make_forward(currency: str, notional_base: float, *, rate: float | None = None,
                 maturity: date | None = None, hedge_id: str | None = None) -> FXHedge:
    return FXHedge(hedge_id or _next_id(), validate_code(currency), float(notional_base),
                   "forward", rate, maturity)


def make_future(currency: str, notional_base: float, *, rate: float | None = None,
                maturity: date | None = None, hedge_id: str | None = None) -> FXHedge:
    return FXHedge(hedge_id or _next_id(), validate_code(currency), float(notional_base),
                   "future", rate, maturity)


def make_swap(currency: str, notional_base: float, *, rate: float | None = None,
              maturity: date | None = None, hedge_id: str | None = None) -> FXHedge:
    return FXHedge(hedge_id or _next_id(), validate_code(currency), float(notional_base),
                   "swap", rate, maturity)


def unhedged_by_currency(book, *, as_of: date | None = None, prices: dict | None = None) -> dict:
    exp = fx_exposure(book, as_of=as_of, prices=prices)
    return {c: e.unhedged_base for c, e in exp.by_currency.items()}
