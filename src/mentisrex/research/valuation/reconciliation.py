"""Valuation reconciliation (AIDP M18).

Compares two sets of `ValuationResult`s — e.g. internal vs an external mark file, or model-A
vs model-B — and reports breaks (missing, price/value mismatch, currency mismatch). Same
spirit as M15/M17 reconciliation, specialised to valuations. Deterministic, tolerance-based.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValuationBreak:
    instrument_id: str
    kind: str  # missing | price_mismatch | value_mismatch | currency_mismatch
    internal: float
    external: float
    detail: str = ""


@dataclass(frozen=True)
class ReconciliationReport:
    breaks: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.breaks

    def of_kind(self, kind: str) -> list:
        return [b for b in self.breaks if b.kind == kind]


def reconcile(
    internal: list, external: dict, *, price_tol: float = 1e-6, value_tol: float = 1e-4
) -> ReconciliationReport:
    """`internal`: list[ValuationResult]. `external`: id -> {"price":, "market_value"?, "currency"?}."""
    breaks = []
    by_id = {r.instrument_id: r for r in internal}
    for iid in sorted(set(by_id) | set(external)):
        r, ext = by_id.get(iid), external.get(iid)
        if r is None:
            breaks.append(
                ValuationBreak(iid, "missing", 0.0, ext.get("price", 0.0), "external only")
            )
            continue
        if ext is None:
            breaks.append(ValuationBreak(iid, "missing", r.price, 0.0, "internal only"))
            continue
        if abs(r.price - ext["price"]) > max(price_tol, abs(ext["price"]) * 1e-6):
            breaks.append(ValuationBreak(iid, "price_mismatch", r.price, ext["price"]))
        if "market_value" in ext and abs(r.market_value - ext["market_value"]) > value_tol:
            breaks.append(
                ValuationBreak(iid, "value_mismatch", r.market_value, ext["market_value"])
            )
        if "currency" in ext and r.currency != ext["currency"]:
            breaks.append(
                ValuationBreak(
                    iid, "currency_mismatch", 0.0, 0.0, f"{r.currency} vs {ext['currency']}"
                )
            )
    return ReconciliationReport(breaks)
