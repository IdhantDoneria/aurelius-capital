"""Deterministic snapshot store (AIDP M20).

A local, dependency-free repository for `SealedSnapshot`s — no external database, no mandatory
parquet. Primary storage is in-memory (the authoritative object graph); an optional directory
persists the *metadata envelope* (ids, fingerprints, quality, versions) as sorted-key JSON for
audit and lookup after a restart. The M18 snapshot object itself is never re-serialized to disk:
it is reproduced deterministically from the message log by the reconstructor, and its fingerprint
is stored so integrity can always be checked.

Lookups: by id, by snapshot fingerprint, by as-of date. Integrity: `verify` recomputes the wrapped
snapshot's fingerprint and the deterministic snapshot id and confirms both — detecting tampering,
truncation and fingerprint mismatch.
"""

from __future__ import annotations

import json
import os
from datetime import date

from mentisrex.research.market_data_ops.lifecycle import SealedSnapshot


class SnapshotStoreError(ValueError):
    pass


class IntegrityError(SnapshotStoreError):
    pass


class SnapshotStore:
    def __init__(self, *, directory: str | None = None) -> None:
        self._by_id: dict[str, SealedSnapshot] = {}
        self._meta: dict[str, dict] = {}  # id -> envelope dict (also what's persisted)
        self.directory = directory
        if directory:
            os.makedirs(directory, exist_ok=True)
            self._load_dir()

    # ── write ────────────────────────────────────────────────────────────────────
    def put(self, sealed: SealedSnapshot) -> str:
        if not sealed.verify():
            raise IntegrityError(
                f"refusing to store snapshot {sealed.snapshot_id}: failed self-verify"
            )
        sid = sealed.snapshot_id
        existing = self._by_id.get(sid)
        if existing is not None and existing.snapshot_fingerprint != sealed.snapshot_fingerprint:
            raise SnapshotStoreError(
                f"id collision: {sid} already stored with a different fingerprint"
            )
        self._by_id[sid] = sealed
        self._meta[sid] = _envelope(sealed)
        if self.directory:
            self._persist(sid)
        return sid

    # ── read ─────────────────────────────────────────────────────────────────────
    def get(self, snapshot_id: str) -> SealedSnapshot:
        s = self._by_id.get(snapshot_id)
        if s is None:
            if snapshot_id in self._meta:
                raise SnapshotStoreError(
                    f"{snapshot_id}: only the metadata envelope is loaded (persisted across a "
                    f"restart). Reconstruct the snapshot from the message log to rehydrate it."
                )
            raise KeyError(f"no snapshot {snapshot_id!r}")
        return s

    def exists(self, snapshot_id: str) -> bool:
        return snapshot_id in self._meta

    def list_ids(self) -> list[str]:
        return sorted(self._meta)

    def metadata(self, snapshot_id: str) -> dict:
        m = self._meta.get(snapshot_id)
        if m is None:
            raise KeyError(f"no snapshot {snapshot_id!r}")
        return dict(m)

    def by_fingerprint(self, snapshot_fingerprint: str) -> list[str]:
        return sorted(
            sid
            for sid, m in self._meta.items()
            if m["snapshot_fingerprint"] == snapshot_fingerprint
        )

    def by_as_of(self, as_of: date) -> list[str]:
        iso = as_of.isoformat()
        return sorted(sid for sid, m in self._meta.items() if m["as_of"] == iso)

    def latest(self, *, as_of: date | None = None) -> SealedSnapshot | None:
        """Most recent (by knowledge_date) in-memory sealed snapshot, optionally for one as-of."""
        cands = [s for s in self._by_id.values() if as_of is None or s.as_of == as_of]
        if not cands:
            return None
        return max(cands, key=lambda s: (s.knowledge_date, s.snapshot_id))

    # ── integrity ──────────────────────────────────────────────────────────────────
    def verify(self, snapshot_id: str) -> bool:
        return self.get(snapshot_id).verify()

    def verify_all(self) -> dict[str, bool]:
        return {sid: s.verify() for sid, s in sorted(self._by_id.items())}

    # ── persistence (metadata envelope only) ─────────────────────────────────────
    def _persist(self, sid: str) -> None:
        path = os.path.join(self.directory, f"{sid}.json")
        with open(path, "w") as f:
            json.dump(self._meta[sid], f, indent=2, sort_keys=True)

    def _load_dir(self) -> None:
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(self.directory, name)) as f:
                env = json.load(f)
            sid = env.get("snapshot_id")
            if sid:
                self._meta[sid] = env


def _envelope(s: SealedSnapshot) -> dict:
    return {
        "snapshot_id": s.snapshot_id,
        "state": s.state.value,
        "as_of": s.as_of.isoformat(),
        "knowledge_date": s.knowledge_date.isoformat(),
        "source_set": list(s.source_set),
        "input_fingerprint": s.input_fingerprint,
        "accepted_fingerprint": s.accepted_fingerprint,
        "rejected_fingerprint": s.rejected_fingerprint,
        "snapshot_fingerprint": s.snapshot_fingerprint,
        "reconstruction_fingerprint": s.reconstruction_fingerprint,
        "pit_status": s.pit_status,
        "quality_summary": dict(s.quality_summary),
        "versions": dict(s.versions),
        "n_observations": s.n_observations,
    }
