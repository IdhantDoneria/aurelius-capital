"""Futures instrument factory + roll helper (AIDP M17).

Margined: no cash at trade, only initial margin posted and daily variation margin as the
mark moves. `roll` expresses the standard close-front / open-back pair as two fills the
book applies atomically.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.instruments.models import (
    CashConvention,
    Instrument,
    InstrumentType,
    SettlementStyle,
)


def future(instrument_id: str, *, currency: str = "USD", exchange: str = "",
           contract_size: float = 1.0, expiry: date | None = None,
           initial_margin_rate: float = 0.05, maintenance_margin_rate: float = 0.04,
           settlement_style: SettlementStyle = SettlementStyle.CASH, **metadata) -> Instrument:
    return Instrument(
        instrument_id=instrument_id, type=InstrumentType.FUTURE, currency=currency,
        exchange=exchange, contract_size=contract_size, expiry=expiry,
        cash_convention=CashConvention.MARGINED, settlement_style=settlement_style,
        initial_margin_rate=initial_margin_rate,
        maintenance_margin_rate=maintenance_margin_rate, metadata=metadata)


def roll(front: Instrument, back: Instrument, quantity: float, *,
         front_price: float, back_price: float):
    """Return the (close-front, open-back) fill pair for rolling `quantity` contracts."""
    return (
        {"instrument": front, "quantity": -quantity, "price": front_price},
        {"instrument": back, "quantity": quantity, "price": back_price},
    )
