"""Point-in-time universe engine (AIDP M4).

Reconstructs the investable universe as of any historical date, survivorship-free.
A security qualifies on `date` iff it had a live listing interval covering that
date in SecurityMaster (`valid_from ≤ date < valid_to`). A delisting closes the
interval, so:
  - a company delisted before `date` is absent (not carried forward),
  - a company that IPO'd after `date` is absent (no future leakage),
  - a company alive on `date` but gone today is present (survivorship-free).

No new interval table: the listing-interval model already IS M2's
security_identity_history (same columns), and the spec forbids duplicate identity
systems. This engine composes over it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class UniverseSnapshot:
    date: date
    securities: list[dict]
    security_count: int
    exclusions: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class UniverseEngine:
    def __init__(self, security_master, *, delisting_store=None, fundamentals=None) -> None:
        self._sm = security_master
        self._delistings = delisting_store
        self._fundamentals = fundamentals

    def universe_as_of(self, as_of: date, *, with_exclusions: bool = False) -> UniverseSnapshot:
        """Securities live on `as_of`. Set with_exclusions to also report which
        registered securities are excluded and why (not_yet_listed / delisted)."""
        live = self._sm.live_as_of(as_of)
        live_ids = {s["security_id"] for s in live}

        exclusions: list[dict] = []
        if with_exclusions:
            for s in self._sm.all_securities():
                if s["security_id"] in live_ids:
                    continue
                # Distinguish future IPO from prior delisting by whether it ever
                # had an interval starting on/before as_of.
                reason = (
                    "delisted"
                    if self._existed_before(s["security_id"], as_of)
                    else "not_yet_listed"
                )
                exclusions.append({**s, "exclusion_reason": reason})

        return UniverseSnapshot(
            date=as_of,
            securities=live,
            security_count=len(live),
            exclusions=exclusions,
            metadata={
                "source": "SecurityMaster.security_identity_history",
                "survivorship_free": True,
                "delisting_events_applied": self._delistings is not None,
            },
        )

    def _existed_before(self, security_id: str, as_of: date) -> bool:
        cur = self._sm.historical_identifier(security_id, as_of)
        if cur is not None:
            return True
        # historical_identifier returns None both for future IPOs and post-delist;
        # check whether any interval began on/before as_of.
        with self._sm._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM security_identity_history WHERE security_id=? AND valid_from <= ? LIMIT 1",
                [security_id, as_of.isoformat()],
            ).fetchone()
        return row is not None
