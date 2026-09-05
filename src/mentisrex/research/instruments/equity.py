"""Equity instrument factory (AIDP M17).

An equity is the degenerate case: contract_size 1, PRINCIPAL cash convention, no expiry.
The M17 book routes equities straight to the reused M15 `PostTradeEngine`, so their
accounting is byte-identical to pre-M17 — this factory only stamps the definition.
"""

from __future__ import annotations

from mentisrex.research.instruments.models import (
    CashConvention,
    Instrument,
    InstrumentType,
)


def equity(
    instrument_id: str,
    *,
    currency: str = "USD",
    exchange: str = "",
    contract_size: float = 1.0,
    **metadata,
) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        type=InstrumentType.EQUITY,
        currency=currency,
        exchange=exchange,
        contract_size=contract_size,
        cash_convention=CashConvention.PRINCIPAL,
        metadata=metadata,
    )
