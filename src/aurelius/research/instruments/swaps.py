"""Swap framework (AIDP M17).

Interest-rate, currency, and equity swaps as a legs + schedule definition. M17 does NOT
price swaps — valuation is delegated to an injected provider (see `valuation.ValuationProvider`).
This module only captures the contract: legs, notional, payment schedule, cash flows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from aurelius.research.instruments.models import (
    CashConvention,
    Instrument,
    InstrumentType,
)


@dataclass(frozen=True)
class SwapLeg:
    leg_id: str
    kind: str                     # "fixed" | "float" | "equity"
    currency: str
    notional: float
    rate: float = 0.0             # fixed rate, or spread for float
    pay: bool = True              # True = we pay this leg, False = we receive


@dataclass(frozen=True)
class CashFlow:
    when: date
    amount: float                 # signed, our perspective
    currency: str
    leg_id: str = ""


@dataclass(frozen=True)
class PaymentSchedule:
    dates: tuple = field(default_factory=tuple)


def swap(instrument_id: str, *, legs: list, currency: str = "USD",
         schedule: PaymentSchedule | None = None, kind: str = "irs", **metadata) -> Instrument:
    md = dict(metadata)
    md["swap_kind"] = kind
    md["legs"] = [leg.__dict__ for leg in legs]
    if schedule is not None:
        md["schedule"] = [d.isoformat() for d in schedule.dates]
    return Instrument(
        instrument_id=instrument_id, type=InstrumentType.SWAP, currency=currency,
        contract_size=1.0, cash_convention=CashConvention.NPV, metadata=md)


def interest_rate_swap(instrument_id: str, *, notional: float, fixed_rate: float,
                       float_spread: float = 0.0, currency: str = "USD", pay_fixed: bool = True):
    fixed = SwapLeg(f"{instrument_id}-fixed", "fixed", currency, notional, fixed_rate, pay_fixed)
    flt = SwapLeg(f"{instrument_id}-float", "float", currency, notional, float_spread, not pay_fixed)
    return swap(instrument_id, legs=[fixed, flt], currency=currency, kind="irs")


def cash_flows(inst: Instrument, provider) -> list:
    """Ask the injected provider for the swap's projected cash flows (list of CashFlow)."""
    return list(provider.cash_flows(inst))
