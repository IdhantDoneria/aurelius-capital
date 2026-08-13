"""Settlement integration (AIDP M17).

Thin bridge over M15 settlement + the M17 expiry/exercise flows. Equity/bond fills settle
through the reused `PostTradeEngine.settle`; derivative expiry/exercise settle via `expiry`.
Cash vs physical is the instrument's `settlement_style`; physical hands off an underlying
fill dict for the caller (or M14 execution) to apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mentisrex.research.instruments import expiry as _expiry
from mentisrex.research.instruments.models import InstrumentType, SettlementStyle


@dataclass(frozen=True)
class SettlementResult:
    instrument_id: str
    style: SettlementStyle
    cash: float
    underlying_fill: dict | None = None


def settle_expiry(book, instrument, settle_price: float, *, when: date | None = None) -> SettlementResult:
    inst = book._inst(instrument)
    res = _expiry.expire(book, inst, settle_price, when=when)
    if inst.type is InstrumentType.OPTION and res is not None:
        return SettlementResult(inst.instrument_id, inst.settlement_style, res.cash, res.underlying_fill)
    return SettlementResult(inst.instrument_id, inst.settlement_style, 0.0)


def settle_cash_book(book, as_of: date) -> list:
    """Advance M15 settlement for the underlying cash book (equities, bond principal)."""
    return book.engine.settle(as_of)
