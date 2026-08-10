"""Contract-spec helpers (AIDP M17).

Small pure helpers over `Instrument` — notional, days-to-expiry, expiry checks. Kept
separate so asset modules stay thin factories and nothing recomputes multipliers ad hoc.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.instruments.models import Instrument


def notional(inst: Instrument, quantity: float, price: float) -> float:
    return inst.notional(quantity, price)


def days_to_expiry(inst: Instrument, as_of: date) -> int | None:
    if inst.expiry is None:
        return None
    return (inst.expiry - as_of).days


def is_expired(inst: Instrument, as_of: date) -> bool:
    return inst.expiry is not None and as_of >= inst.expiry
