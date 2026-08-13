"""Expiry handling (AIDP M17).

At expiry: options settle via `exercise` (ITM → exercise/assign, OTM → worthless), futures
and forwards cash/physical settle at the final mark, everything else terminates. `expire`
is the one entry point the lifecycle/settlement layers call at contract maturity.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.instruments import exercise as _exercise
from mentisrex.research.instruments.contracts import is_expired
from mentisrex.research.instruments.models import InstrumentEventType, InstrumentType


def expire(book, instrument, settle_price: float, *, when: date | None = None):
    """Settle a contract at expiry. Returns the exercise result for options, else None."""
    inst = book._inst(instrument)
    if inst.type is InstrumentType.OPTION:
        return _exercise.exercise(book, inst, settle_price, when=when)
    # futures / forwards: final MTM then flatten at settle price
    book.mark({inst.instrument_id: settle_price}, when=when)
    book.close(inst, settle_price, when=when)
    book._closed.add(inst.instrument_id)
    book._emit(InstrumentEventType.EXPIRY, inst.instrument_id, price=settle_price, when=when)
    return None


def expiring_on(book, as_of: date) -> list:
    """Instrument ids with an open position expiring on/before `as_of`."""
    return [iid for iid, p in book.positions.items()
            if p.quantity != 0 and iid not in book._closed
            and is_expired(book.registry.get(iid), as_of)]
