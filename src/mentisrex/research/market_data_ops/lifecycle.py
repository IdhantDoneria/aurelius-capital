"""Snapshot lifecycle (AIDP M20).

A market-data snapshot travels an explicit state machine — RAW → NORMALIZED → QUALITY_CHECKED →
PIT_VALIDATED → ASSEMBLED → SEALED (or REJECTED). M20 makes the terminal states first-class: a
`SealedSnapshot` is an immutable, fully-attributed record wrapping the M18 `MarketDataSnapshot`
plus the provenance a governance audit needs — snapshot id, as-of, knowledge date, source set,
input/accepted/rejected fingerprints, quality summary, PIT status and component versions.

Sealing is one-way: the wrapper is a frozen dataclass, so once sealed the state cannot be mutated.
The wrapped M18 snapshot was already immutable; sealing adds the operational envelope around it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from mentisrex.research.market_data_ops.reconstruction import ReconstructionResult


class SnapshotState(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    QUALITY_CHECKED = "quality_checked"
    PIT_VALIDATED = "pit_validated"
    ASSEMBLED = "assembled"
    SEALED = "sealed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SealedSnapshot:
    """Immutable sealed record. `snapshot` is the M18 object the valuation engine consumes; the
    rest is the operational envelope. Equality/reproducibility hinge on `snapshot_id`, which is a
    deterministic function of the content."""

    snapshot_id: str
    state: SnapshotState
    as_of: date
    knowledge_date: date
    snapshot: object  # M18 MarketDataSnapshot
    source_set: tuple = ()
    input_fingerprint: str = ""
    accepted_fingerprint: str = ""
    rejected_fingerprint: str = ""
    snapshot_fingerprint: str = ""
    reconstruction_fingerprint: str = ""
    pit_status: str = "unknown"  # clean | look_ahead | stale
    quality_summary: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)
    n_observations: int = 0

    def verify(self) -> bool:
        """Re-derive the sealed fingerprints from the wrapped snapshot and confirm they match —
        tamper/corruption detection for a stored sealed snapshot."""
        return (
            self.snapshot_fingerprint == self.snapshot.fingerprint()
            and self.snapshot_id
            == _seal_id(
                self.as_of,
                self.knowledge_date,
                self.reconstruction_fingerprint,
                self.snapshot_fingerprint,
            )
        )


_DEFAULT_VERSIONS = {"m19": "1.0.0", "m20": "1.0.0", "m18_compat": "1.0.0"}


def seal(
    result: ReconstructionResult,
    *,
    versions: dict | None = None,
    calendar_version: str = "",
    identifier_map_version: str = "",
) -> SealedSnapshot:
    """Seal a reconstruction into an immutable, fully-attributed record."""
    snap = result.snapshot
    winners = result.winners
    sources = tuple(sorted({w.source for w in winners}))

    accepted_fp = _hash_fps(w.raw_fingerprint() for w in winners)
    input_fp = result.fingerprint
    rejected_fp = _hash_strs(str(d) for d in result.diagnostics)
    snap_fp = snap.fingerprint()

    pit_status = "clean"
    for d in result.diagnostics:
        s = str(d).lower()
        if "look-ahead" in s or "look_ahead" in s:
            pit_status = "look_ahead"
            break
        if "stale" in s and pit_status == "clean":
            pit_status = "stale"

    quality_summary = _summarize(result.diagnostics)
    vers = {**_DEFAULT_VERSIONS, **(versions or {})}
    if calendar_version:
        vers["calendar"] = calendar_version
    if identifier_map_version:
        vers["identifier_map"] = identifier_map_version

    sid = _seal_id(result.valuation_date, result.knowledge_date, result.fingerprint, snap_fp)
    return SealedSnapshot(
        snapshot_id=sid,
        state=SnapshotState.SEALED,
        as_of=result.valuation_date,
        knowledge_date=result.knowledge_date,
        snapshot=snap,
        source_set=sources,
        input_fingerprint=input_fp,
        accepted_fingerprint=accepted_fp,
        rejected_fingerprint=rejected_fp,
        snapshot_fingerprint=snap_fp,
        reconstruction_fingerprint=result.fingerprint,
        pit_status=pit_status,
        quality_summary=quality_summary,
        versions=vers,
        n_observations=len(winners),
    )


def reject(result: ReconstructionResult, reason: str) -> SealedSnapshot:
    """Produce a REJECTED terminal record (still immutable and attributed)."""
    s = seal(result)
    from dataclasses import replace

    return replace(
        s,
        state=SnapshotState.REJECTED,
        quality_summary={**s.quality_summary, "rejection_reason": reason},
    )


# ── helpers ────────────────────────────────────────────────────────────────────


def _seal_id(as_of, knowledge_date, recon_fp, snap_fp) -> str:
    return hashlib.blake2b(
        f"{as_of}|{knowledge_date}|{recon_fp}|{snap_fp}".encode(), digest_size=8
    ).hexdigest()


def _hash_fps(fps) -> str:
    h = hashlib.blake2b(digest_size=8)
    for fp in sorted(fps):
        h.update(fp.encode())
    return h.hexdigest()


def _hash_strs(strs) -> str:
    h = hashlib.blake2b(digest_size=8)
    for s in sorted(strs):
        h.update(s.encode())
    return h.hexdigest()


def _summarize(diagnostics) -> dict:
    out: dict = {"n_diagnostics": len(diagnostics)}
    for d in diagnostics:
        sev = getattr(getattr(d, "severity", None), "value", None)
        if sev:
            out[sev] = out.get(sev, 0) + 1
    return out
