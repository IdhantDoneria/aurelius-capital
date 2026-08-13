"""Revision / restatement handling (AIDP M19).

Institutional data is not immutable: a fundamental, a macro print, even a corrected close gets
restated after first publication. A bitemporal store separates two questions that are easy to
conflate and dangerous to mix in research:

  - **known_as_of(effective_date, knowledge_date)** — "what did Mentisrex *know* on that day?"
    (uses only revisions published on/before knowledge_date — the PIT-safe answer)
  - **current(effective_date)** — "what is the latest *revised* value for that date?"
    (fine for reporting, look-ahead for backtests)

Append-only: a restatement adds a new `RevisionRecord`, it never mutates the prior one, so the
full audit trail survives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RevisionRecord:
    security_id: str
    field: str
    effective_date: date          # the date the value is FOR
    value: float
    knowledge_date: date          # the date the value was published/known
    revision: int = 0             # monotone per (security_id, field, effective_date)
    source: str = "unknown"


class RevisionStore:
    """Append-only bitemporal store keyed on (security_id, field, effective_date)."""

    def __init__(self) -> None:
        self._records: dict[tuple, list[RevisionRecord]] = {}

    def record(self, security_id: str, field: str, effective_date: date, value: float, *,
               knowledge_date: date, source: str = "unknown") -> RevisionRecord:
        key = (security_id, field, effective_date)
        seq = self._records.setdefault(key, [])
        rev = RevisionRecord(security_id, field, effective_date, float(value),
                             knowledge_date, len(seq), source)
        seq.append(rev)
        return rev

    def history(self, security_id: str, field: str, effective_date: date) -> list[RevisionRecord]:
        return list(self._records.get((security_id, field, effective_date), ()))

    def known_as_of(self, security_id: str, field: str, effective_date: date,
                    knowledge_date: date) -> RevisionRecord | None:
        """The value Mentisrex knew on `knowledge_date` — latest revision published by then."""
        best = None
        for r in self._records.get((security_id, field, effective_date), ()):
            if r.knowledge_date <= knowledge_date:
                if best is None or r.knowledge_date >= best.knowledge_date:
                    best = r
        return best

    def current(self, security_id: str, field: str, effective_date: date) -> RevisionRecord | None:
        """The latest revised value regardless of when it was published (look-ahead — reporting)."""
        seq = self._records.get((security_id, field, effective_date))
        return seq[-1] if seq else None

    def was_restated(self, security_id: str, field: str, effective_date: date) -> bool:
        return len(self._records.get((security_id, field, effective_date), ())) > 1
