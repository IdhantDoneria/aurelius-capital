"""Option exercise & assignment (AIDP M17).

European only: at (or after) expiry, an in-the-money option is exercised (long) / assigned
(short). Cash settlement pays intrinsic value through the M11 ledger and flattens the
position; physical settlement is an interface that hands off an equity fill in the
underlying. Out-of-the-money → expire worthless (see `expiry.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aurelius.research.instruments.options import intrinsic_value
from aurelius.research.instruments.models import (
    ExerciseStatus,
    InstrumentEventType,
    InstrumentType,
    OptionRight,
    SettlementStyle,
)


@dataclass(frozen=True)
class ExerciseResult:
    instrument_id: str
    status: ExerciseStatus
    quantity: float
    intrinsic: float
    cash: float
    underlying_fill: dict | None = None      # physical settlement hand-off


def exercise(book, instrument, spot: float, *, when: date | None = None) -> ExerciseResult:
    """Settle a European option at `spot`. Long ITM → exercise, short ITM → assignment."""
    inst = book._inst(instrument)
    if inst.type is not InstrumentType.OPTION:
        raise ValueError(f"{inst.instrument_id} is not an option")
    pos = book.positions.get(inst.instrument_id)
    qty = pos.quantity if pos else 0.0
    iv = intrinsic_value(inst, spot)

    if qty == 0 or iv <= 0:
        if qty != 0:                          # OTM: close at 0 so the premium P&L realizes
            book.book_trade(inst, -qty, 0.0, trade_date=when)
        book._closed.add(inst.instrument_id)
        book._emit(InstrumentEventType.EXPIRY, inst.instrument_id, price=spot, when=when,
                   detail="worthless")
        return ExerciseResult(inst.instrument_id, ExerciseStatus.EXPIRED, qty, iv, 0.0)

    status = ExerciseStatus.EXERCISED if qty > 0 else ExerciseStatus.ASSIGNED
    et = InstrumentEventType.EXERCISE if qty > 0 else InstrumentEventType.ASSIGNMENT

    underlying_fill = None
    if inst.settlement_style is SettlementStyle.PHYSICAL:
        # deliver the underlying: long call / short put receive shares, etc. Sign per right.
        direction = 1 if inst.right is OptionRight.CALL else -1
        underlying_fill = {"security_id": inst.underlying,
                           "quantity": direction * qty * inst.contract_size,
                           "price": inst.strike}

    # Flatten the option at intrinsic. Under PRINCIPAL convention this single close IS the
    # cash settlement: sell-to-close at intrinsic pays the long / charges the short exactly
    # `iv * qty * contract_size` — no separate settlement post (that would double-count).
    cash = iv * qty * inst.contract_size
    book.book_trade(inst, -qty, iv, trade_date=when)
    book._closed.add(inst.instrument_id)
    book._emit(et, inst.instrument_id, quantity=qty, price=spot, cash=cash, when=when)
    return ExerciseResult(inst.instrument_id, status, qty, iv, cash, underlying_fill)
