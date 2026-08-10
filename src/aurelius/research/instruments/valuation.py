"""Valuation via dependency-injected providers (AIDP M17).

Every valuation requires instrument + date + market inputs + currency + provider — nothing
is hard-coded. `MarkProvider`/`PricingProvider` supply the per-unit mark; this module turns
it into market value and unrealized P&L, optionally converting to a base currency through
an M16 FX provider so multi-currency derivatives value consistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aurelius.research.instruments import instrument as _econ
from aurelius.research.instruments.models import Instrument


class MarkProvider(Protocol):
    def mark(self, inst: Instrument, market: dict) -> float: ...


@dataclass(frozen=True)
class ValuationResult:
    instrument_id: str
    quantity: float
    mark: float
    market_value: float
    unrealized_pnl: float
    currency: str
    base_market_value: float
    base_currency: str


def mark_of(inst: Instrument, market: dict, provider) -> float:
    """Per-unit mark from whichever provider interface the caller injected."""
    if hasattr(provider, "mark"):
        return float(provider.mark(inst, market))
    return float(provider.price(inst, market))


def value_position(inst: Instrument, quantity: float, avg_price: float, market: dict,
                   provider, *, base_currency: str | None = None, fx_provider=None) -> ValuationResult:
    mark = mark_of(inst, market, provider)
    mv = _econ.position_value(inst, quantity, mark)
    upnl = _econ.unrealized_pnl(inst, quantity, avg_price, mark)
    base = base_currency or inst.currency
    rate = 1.0
    if base != inst.currency:
        if fx_provider is None:
            raise ValueError(f"need fx_provider to value {inst.currency} in {base}")
        rate = fx_provider.rate(inst.currency, base)
    return ValuationResult(inst.instrument_id, quantity, mark, mv, upnl, inst.currency,
                           mv * rate, base)
