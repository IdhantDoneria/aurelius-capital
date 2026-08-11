"""Incremental ingestion (AIDP M20).

Market-data state accretes: new batches bring new observations, revisions, corrections, late data
and deletions. `MarketDataState` is an append-only, fingerprint-deduplicated message log that can
reconstruct a PIT snapshot at any (valuation, knowledge) pair on demand.

The central guarantee — tested exhaustively — is that **incremental equals full rebuild**: because
reconstruction is a pure function of the deduplicated message *set*, ingesting batches one at a
time and reconstructing yields byte-identical state (same snapshot fingerprint) to ingesting the
union at once. Late and out-of-order data therefore cannot produce a path-dependent state.
Deletions are modelled as tombstone messages, which the reconstructor removes from the winners.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from aurelius.research.market_data_ops.lifecycle import SealedSnapshot, seal
from aurelius.research.market_data_ops.messages import (
    MessageType,
    SourceMessage,
)
from aurelius.research.market_data_ops.reconstruction import (
    HistoricalReconstructor,
    ReconstructionResult,
)


@dataclass(frozen=True)
class IngestReport:
    added: int = 0
    duplicates: int = 0
    total: int = 0
    state_fingerprint: str = ""


class MarketDataState:
    """Append-only deduplicated message log with on-demand PIT reconstruction."""

    def __init__(self, *, reconstructor: HistoricalReconstructor | None = None) -> None:
        self.reconstructor = reconstructor or HistoricalReconstructor()
        self._messages: list[SourceMessage] = []
        self._fps: set[str] = set()

    def ingest(self, batch) -> IngestReport:
        added = dups = 0
        for m in batch:
            fp = m.raw_fingerprint()
            if fp in self._fps:
                dups += 1
                continue
            self._fps.add(fp)
            self._messages.append(m)
            added += 1
        return IngestReport(added, dups, len(self._messages), self.fingerprint())

    def tombstone(self, *, security_id: str, field: str, effective_date: date,
                  source: str = "m20", knowledge_date: date | None = None) -> IngestReport:
        """Record a deletion of a prior observation as a tombstone message."""
        msg = SourceMessage(
            source=source, msg_type=MessageType.TOMBSTONE,
            payload={"id": security_id, "field": field,
                     "effective_date": effective_date.isoformat()},
            observation_date=knowledge_date or effective_date, effective_date=effective_date)
        return self.ingest([msg])

    @property
    def messages(self) -> tuple:
        return tuple(self._messages)

    def fingerprint(self) -> str:
        """Order-independent hash of the message set — identical for any ingestion order."""
        h = hashlib.blake2b(digest_size=16)
        for fp in sorted(self._fps):
            h.update(fp.encode())
        return h.hexdigest()

    def reconstruct(self, *, valuation_date: date, knowledge_date: date | None = None,
                    **kwargs) -> ReconstructionResult:
        return self.reconstructor.reconstruct(
            self._messages, valuation_date=valuation_date, knowledge_date=knowledge_date, **kwargs)

    def seal(self, *, valuation_date: date, knowledge_date: date | None = None,
             versions: dict | None = None, **kwargs) -> SealedSnapshot:
        rec = self.reconstruct(valuation_date=valuation_date, knowledge_date=knowledge_date, **kwargs)
        return seal(rec, versions=versions)
