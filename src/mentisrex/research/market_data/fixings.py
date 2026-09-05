"""Market fixings (AIDP M19).

Canonical, PIT-aware fixing store for overnight rates (SOFR/ESTR/SONIA-style), benchmark rates,
FX fixings and reference fixings. Every fixing is dated, sourced, versioned (revisions) and only
visible to a query once it was known — the store answers "what fixing did we have on knowledge
date K for fixing date F?" so historical reconstruction stays honest. Backed by the bitemporal
`RevisionStore`, so a corrected fixing never overwrites the original.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from mentisrex.research.market_data.revisions import RevisionStore


class FixingType(StrEnum):
    OVERNIGHT = "overnight"  # SOFR/ESTR/SONIA/FedFunds
    BENCHMARK = "benchmark"  # term reference rate
    FX = "fx"  # WM/Reuters-style FX fix
    REFERENCE = "reference"  # commodity/index reference


@dataclass(frozen=True)
class Fixing:
    index: str  # "SOFR", "EUR/USD", ...
    fixing_date: date
    value: float
    fixing_type: FixingType = FixingType.OVERNIGHT
    currency: str | None = None
    source: str = "unknown"
    revision: int = 0


class FixingStore:
    """PIT-aware, versioned fixing store."""

    def __init__(self) -> None:
        self._store = RevisionStore()
        self._types: dict[str, FixingType] = {}
        self._ccy: dict[str, str | None] = {}

    def add(
        self,
        index: str,
        fixing_date: date,
        value: float,
        *,
        knowledge_date: date | None = None,
        fixing_type: FixingType = FixingType.OVERNIGHT,
        currency: str | None = None,
        source: str = "unknown",
    ) -> Fixing:
        # a fixing is knowable on its fixing date at the earliest unless stated otherwise
        kd = knowledge_date or fixing_date
        rec = self._store.record(
            index, "fixing", fixing_date, value, knowledge_date=kd, source=source
        )
        self._types[index] = FixingType(fixing_type)
        self._ccy[index] = currency
        return Fixing(index, fixing_date, value, self._types[index], currency, source, rec.revision)

    def get(self, index: str, fixing_date: date, *, as_of: date | None = None) -> Fixing:
        """The fixing for `fixing_date` as known on `as_of` (PIT). Raises if none knowable yet."""
        if as_of is None:
            rec = self._store.current(index, "fixing", fixing_date)
        else:
            rec = self._store.known_as_of(index, "fixing", fixing_date, as_of)
        if rec is None:
            raise KeyError(f"no {index} fixing for {fixing_date} knowable as_of {as_of}")
        return Fixing(
            index,
            fixing_date,
            rec.value,
            self._types.get(index, FixingType.OVERNIGHT),
            self._ccy.get(index),
            rec.source,
            rec.revision,
        )

    def history(self, index: str, fixing_date: date) -> list:
        return self._store.history(index, "fixing", fixing_date)
