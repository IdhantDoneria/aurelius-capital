"""Option instrument factory (AIDP M17).

European calls/puts, long or short. Premium is PRINCIPAL: a long pays premium at trade
(cash out), a short receives it — the sign falls out of the fill quantity, exactly like an
equity, so no special premium accounting is needed. Exercise/assignment/expiry live in
`exercise.py` / `expiry.py`.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.instruments.models import (
    CashConvention,
    ExerciseStyle,
    Instrument,
    InstrumentType,
    OptionRight,
    SettlementStyle,
)


def option(
    instrument_id: str,
    *,
    underlying: str,
    strike: float,
    expiry: date,
    right: OptionRight | str,
    currency: str = "USD",
    exchange: str = "",
    contract_size: float = 100.0,
    settlement_style: SettlementStyle = SettlementStyle.CASH,
    **metadata,
) -> Instrument:
    right = OptionRight(right) if isinstance(right, str) else right
    if strike <= 0:
        raise ValueError("strike must be > 0")
    return Instrument(
        instrument_id=instrument_id,
        type=InstrumentType.OPTION,
        currency=currency,
        exchange=exchange,
        contract_size=contract_size,
        expiry=expiry,
        cash_convention=CashConvention.PRINCIPAL,
        settlement_style=settlement_style,
        underlying=underlying,
        strike=strike,
        right=right,
        exercise_style=ExerciseStyle.EUROPEAN,
        metadata=metadata,
    )


def call(instrument_id: str, **kw) -> Instrument:
    return option(instrument_id, right=OptionRight.CALL, **kw)


def put(instrument_id: str, **kw) -> Instrument:
    return option(instrument_id, right=OptionRight.PUT, **kw)


def intrinsic_value(inst: Instrument, spot: float) -> float:
    """Per-unit intrinsic value of the option at `spot` (never negative)."""
    if inst.right is OptionRight.CALL:
        return max(0.0, spot - inst.strike)
    return max(0.0, inst.strike - spot)


def is_in_the_money(inst: Instrument, spot: float, tol: float = 0.0) -> bool:
    return intrinsic_value(inst, spot) > tol
