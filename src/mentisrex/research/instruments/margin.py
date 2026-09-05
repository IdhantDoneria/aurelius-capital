"""Margin engine (AIDP M17).

Initial + maintenance margin from an instrument's rates and current notional, plus margin
calls when posted margin falls under maintenance. Rates are instrument-level and injectable;
integrates with M13 by exposing margin as an exposure (see `risk.py`). No pricing here —
notional is (quantity * mark * contract_size).
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.instruments.models import Instrument, MarginRequirement


def requirement(inst: Instrument, quantity: float, mark: float) -> MarginRequirement:
    notional = abs(quantity) * mark * inst.contract_size
    return MarginRequirement(
        instrument_id=inst.instrument_id,
        initial=notional * inst.initial_margin_rate,
        maintenance=notional * inst.maintenance_margin_rate,
        currency=inst.currency,
    )


@dataclass(frozen=True)
class MarginCall:
    instrument_id: str
    posted: float
    maintenance: float
    shortfall: float
    currency: str

    @property
    def breached(self) -> bool:
        return self.shortfall > 1e-9


def check_call(inst: Instrument, quantity: float, mark: float, posted: float) -> MarginCall:
    req = requirement(inst, quantity, mark)
    return MarginCall(
        inst.instrument_id,
        posted,
        req.maintenance,
        max(0.0, req.maintenance - posted),
        inst.currency,
    )


def liquidation_warning(call: MarginCall, *, buffer: float = 0.0) -> bool:
    """True when the shortfall exceeds `buffer` — the hook a liquidation policy consumes."""
    return call.shortfall > buffer
