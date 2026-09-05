"""Reconciliation (AIDP M17).

Compares the internal instrument book against external records (broker / clearing /
settlement / margin / collateral). Deterministic, tolerance-based; returns a list of typed
breaks. Same spirit as M15/M16 reconciliation, generalised to contracts + margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Break:
    instrument_id: str
    kind: str  # missing_contract | wrong_quantity | wrong_valuation |
    # wrong_margin | missing_exercise | settlement_mismatch
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


def reconcile_positions(
    book, external: dict, *, marks: dict | None = None, tol: float = 1e-6
) -> ReconciliationReport:
    """`external`: instrument_id -> {"quantity": q, "valuation": v?, "margin": m?}."""
    marks = marks or {}
    breaks = []
    internal = {p.instrument_id: p for p in book.open_positions()}

    for iid, ext in sorted(external.items()):
        pos = internal.get(iid)
        if pos is None:
            breaks.append(
                Break(
                    iid,
                    "missing_contract",
                    0.0,
                    ext.get("quantity", 0.0),
                    "in external, not in book",
                )
            )
            continue
        if abs(pos.quantity - ext.get("quantity", pos.quantity)) > tol:
            breaks.append(Break(iid, "wrong_quantity", pos.quantity, ext["quantity"]))
        if "valuation" in ext:
            iv = pos.market_value
            if abs(iv - ext["valuation"]) > max(tol, abs(ext["valuation"]) * 1e-6):
                breaks.append(Break(iid, "wrong_valuation", iv, ext["valuation"]))
        if "margin" in ext:
            im = book.margin_posted.get(iid, 0.0)
            if abs(im - ext["margin"]) > tol:
                breaks.append(Break(iid, "wrong_margin", im, ext["margin"]))

    for iid, pos in sorted(internal.items()):  # book has it, external doesn't
        if iid not in external:
            breaks.append(
                Break(iid, "missing_contract", pos.quantity, 0.0, "in book, not in external")
            )
    return ReconciliationReport(breaks)


def reconcile_settlement(book, settled_ids: set, *, expected_closed: set) -> ReconciliationReport:
    """Flag contracts that should have settled/exercised but did not (missing_exercise)."""
    breaks = [
        Break(iid, "missing_exercise", 0.0, 0.0, "expected settled, still open")
        for iid in sorted(expected_closed)
        if iid not in settled_ids and iid not in book._closed
    ]
    return ReconciliationReport(breaks)
