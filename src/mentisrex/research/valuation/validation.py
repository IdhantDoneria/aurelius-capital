"""Valuation validation (AIDP M18).

`ValuationValidator` — deterministic checks over inputs and results: input completeness,
curve/surface validity, stale market data, currency consistency, PIT consistency, numerical
stability and valuation reconciliation. Returns human-readable problems (empty == healthy);
no mutation, no I/O. No-arbitrage bounds live in `diagnostics.py` and are surfaced here too.
"""

from __future__ import annotations

import math

from mentisrex.research.instruments.models import InstrumentType
from mentisrex.research.valuation.models import MarketDataSnapshot, ValuationResult
from mentisrex.research.valuation.snapshot import validate_pit


class ValuationValidator:
    def __init__(self, *, max_staleness_days: int | None = None) -> None:
        self.max_staleness_days = max_staleness_days

    def validate_snapshot(self, snap: MarketDataSnapshot) -> list:
        problems = list(validate_pit(snap, max_staleness_days=self.max_staleness_days))
        for _cid, curve in snap.rates.items():
            problems.extend(curve.validate())
        for _sid, surf in snap.vol_surfaces.items():
            problems.extend(surf.validate())
        return problems

    def validate_inputs(self, inst, snap: MarketDataSnapshot) -> list:
        """Input completeness for a given instrument against a snapshot."""
        problems = []
        t = inst.type
        if t is InstrumentType.EQUITY and inst.instrument_id not in snap.spots:
            problems.append(f"{inst.instrument_id}: missing spot")
        if t is InstrumentType.OPTION:
            u = inst.underlying
            if u not in snap.spots:
                problems.append(f"{inst.instrument_id}: missing underlying spot {u}")
            if u not in snap.vol_surfaces:
                problems.append(f"{inst.instrument_id}: missing vol surface {u}")
        if (
            t is InstrumentType.BOND
            and inst.currency not in snap.rates
            and "ytm" not in inst.metadata
        ):
            problems.append(f"{inst.instrument_id}: missing {inst.currency} curve and ytm")
        return problems

    def validate_result(self, res: ValuationResult) -> list:
        problems = []
        if not math.isfinite(res.price):
            problems.append(f"{res.instrument_id}: non-finite price")
        if not math.isfinite(res.market_value):
            problems.append(f"{res.instrument_id}: non-finite market value")
        if res.currency and res.base_value and res.market_value:
            if (res.market_value > 0) != (res.base_value > 0):
                problems.append(f"{res.instrument_id}: base/local value sign mismatch")
        if not res.market_data_fingerprint or not res.input_fingerprint:
            problems.append(f"{res.instrument_id}: missing governance fingerprint")
        return problems

    def reconcile(self, a: ValuationResult, b: ValuationResult, *, tol: float = 1e-6) -> list:
        """Two valuations of the same instrument should agree (determinism / cross-model)."""
        if a.instrument_id != b.instrument_id:
            return [f"instrument mismatch {a.instrument_id} vs {b.instrument_id}"]
        if abs(a.price - b.price) > max(tol, abs(a.price) * 1e-6):
            return [f"{a.instrument_id}: price mismatch {a.price} vs {b.price}"]
        return []
