"""Forward instrument factory (AIDP M17).

Currency and commodity forwards. Margined-style: no cash at inception, MTM to the
prevailing forward mark, settle the difference at the settlement date. FX forwards carry
their currency pair in metadata and value through M16 (see `valuation.py` / risk).
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.instruments.models import (
    CashConvention,
    Instrument,
    InstrumentType,
    SettlementStyle,
)


def forward(
    instrument_id: str,
    *,
    currency: str = "USD",
    contract_size: float = 1.0,
    settlement_date: date | None = None,
    forward_price: float | None = None,
    settlement_style: SettlementStyle = SettlementStyle.CASH,
    **metadata,
) -> Instrument:
    md = dict(metadata)
    if forward_price is not None:
        md["forward_price"] = forward_price
    return Instrument(
        instrument_id=instrument_id,
        type=InstrumentType.FORWARD,
        currency=currency,
        contract_size=contract_size,
        expiry=settlement_date,
        cash_convention=CashConvention.MARGINED,
        settlement_style=settlement_style,
        metadata=md,
    )


def fx_forward(
    instrument_id: str,
    *,
    base: str,
    quote: str,
    notional: float,
    forward_rate: float,
    settlement_date: date,
) -> Instrument:
    """A currency forward: buy `notional` of `base`, pay in `quote` at `forward_rate`."""
    return forward(
        instrument_id,
        currency=quote,
        contract_size=notional,
        settlement_date=settlement_date,
        forward_price=forward_rate,
        pair=f"{base}/{quote}",
        base=base,
        quote=quote,
    )
