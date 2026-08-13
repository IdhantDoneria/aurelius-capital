"""Fixed-income instrument model (AIDP M17).

Bonds as principal instruments quoted as a price per 100 face; contract_size carries the
face value / 100, so `trade_cash` yields the right principal with no special case. Coupon
schedule, yield and duration are *interfaces* — M17 generates the coupon cash-flow dates
and defers pricing/duration to an injected `YieldProvider`.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.instruments.models import (
    CashConvention,
    Instrument,
    InstrumentType,
)


def bond(instrument_id: str, *, face: float = 100.0, coupon: float = 0.0,
         maturity: date | None = None, frequency: int = 2, currency: str = "USD",
         **metadata) -> Instrument:
    """A bond quoted per 100 face. `coupon` is the annual rate (0.04 = 4%)."""
    md = dict(metadata)
    md.update(coupon=coupon, face=face, frequency=frequency)
    return Instrument(
        instrument_id=instrument_id, type=InstrumentType.BOND, currency=currency,
        contract_size=face / 100.0, expiry=maturity,
        cash_convention=CashConvention.PRINCIPAL, metadata=md)


def coupon_schedule(inst: Instrument, *, issue: date) -> list:
    """Coupon payment dates from `issue` to maturity at the bond's frequency."""
    if inst.expiry is None:
        return []
    freq = int(inst.metadata.get("frequency", 2)) or 1
    step = 12 // freq
    dates, d = [], issue
    while True:
        # advance `step` months
        month = d.month - 1 + step
        d = date(d.year + month // 12, month % 12 + 1, min(d.day, 28))
        if d >= inst.expiry:
            dates.append(inst.expiry)
            break
        dates.append(d)
    return dates


def coupon_cash_flows(inst: Instrument, *, issue: date, quantity: float = 1.0) -> list:
    """(date, amount) coupon payments for `quantity` bonds — deterministic, no pricing."""
    rate = float(inst.metadata.get("coupon", 0.0))
    freq = int(inst.metadata.get("frequency", 2)) or 1
    face = float(inst.metadata.get("face", 100.0))
    per = rate / freq * face * quantity
    return [(d, per) for d in coupon_schedule(inst, issue=issue)]


def yield_to_maturity(inst: Instrument, price: float, provider) -> float:
    """Delegated to the injected YieldProvider — M17 does not implement bond math."""
    return provider.ytm(inst, price)


def duration(inst: Instrument, price: float, provider) -> float:
    return provider.duration(inst, price)
