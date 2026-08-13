"""Instrument registry (AIDP M17).

A deterministic id -> `Instrument` catalog. Immutable inserts (re-registering the same id
with a different definition is an error), sorted iteration, type filters. This is the
book's source of instrument truth — positions and events reference ids, definitions live
here once.
"""

from __future__ import annotations

from mentisrex.research.instruments.models import Instrument, InstrumentType


class InstrumentRegistry:
    def __init__(self) -> None:
        self._by_id: dict = {}

    def register(self, inst: Instrument) -> Instrument:
        existing = self._by_id.get(inst.instrument_id)
        if existing is not None and existing != inst:
            raise ValueError(f"instrument {inst.instrument_id!r} already registered differently")
        self._by_id[inst.instrument_id] = inst
        return inst

    def get(self, instrument_id: str) -> Instrument:
        try:
            return self._by_id[instrument_id]
        except KeyError:
            raise KeyError(f"unknown instrument {instrument_id!r}") from None

    def has(self, instrument_id: str) -> bool:
        return instrument_id in self._by_id

    def all(self) -> list:
        return [self._by_id[k] for k in sorted(self._by_id)]

    def of_type(self, t: InstrumentType) -> list:
        return [i for i in self.all() if i.type is t]

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, instrument_id: str) -> bool:
        return instrument_id in self._by_id
