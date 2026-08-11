"""Ops component registry & artifact lineage (AIDP M20).

Reuses M19's `MarketDataRegistry` (no second registry is created) and adds the M20 operational
components to it, plus a `SnapshotLineage` record that ties a sealed snapshot to every fingerprint
and version that produced it — source set, input/accepted fingerprints, arbitration & ordering
policy fingerprints, snapshot fingerprint and component versions. That record is what a governance
audit or an experiment-lineage attachment consumes.
"""

from __future__ import annotations

from dataclasses import dataclass

from aurelius.research.market_data.registry import (
    ComponentInfo,
    ComponentKind,
    MarketDataRegistry,
    default_market_data_registry,
)
from aurelius.research.market_data_ops.lifecycle import SealedSnapshot


@dataclass(frozen=True)
class SnapshotLineage:
    """Full provenance chain for one sealed snapshot — reproducible from these fingerprints."""
    snapshot_id: str
    as_of: str
    knowledge_date: str
    source_set: tuple
    snapshot_fingerprint: str
    input_fingerprint: str
    accepted_fingerprint: str
    reconstruction_fingerprint: str
    arbitration_fingerprint: str
    versions: dict


def lineage_of(sealed: SealedSnapshot, *, arbitration_fingerprint: str = "") -> SnapshotLineage:
    return SnapshotLineage(
        snapshot_id=sealed.snapshot_id, as_of=sealed.as_of.isoformat(),
        knowledge_date=sealed.knowledge_date.isoformat(), source_set=tuple(sealed.source_set),
        snapshot_fingerprint=sealed.snapshot_fingerprint,
        input_fingerprint=sealed.input_fingerprint,
        accepted_fingerprint=sealed.accepted_fingerprint,
        reconstruction_fingerprint=sealed.reconstruction_fingerprint,
        arbitration_fingerprint=arbitration_fingerprint, versions=dict(sealed.versions))


def default_ops_registry() -> MarketDataRegistry:
    """The M19 registry extended with the M20 operational components (registered under the existing
    PROVIDER kind so no M19 enum is modified)."""
    r = default_market_data_registry()
    for info in (
        ComponentInfo(ComponentKind.PROVIDER, "ops.local_adapter", "1.0.0",
                      "M19 source wrapped as operational adapter"),
        ComponentInfo(ComponentKind.PROVIDER, "ops.message_log", "1.0.0",
                      "Ordered message-log replay source"),
        ComponentInfo(ComponentKind.PROVIDER, "ops.fixture_vendor", "1.0.0",
                      "Recorded vendor fixtures for offline contract tests"),
        ComponentInfo(ComponentKind.PROVIDER, "ops.production_contract", "1.0.0",
                      "Live vendor adapter contract (offline, transport raises)"),
        ComponentInfo(ComponentKind.PROVIDER, "ops.replay_engine", "1.0.0",
                      "Deterministic historical replay"),
        ComponentInfo(ComponentKind.PROVIDER, "ops.reconstructor", "1.0.0",
                      "PIT snapshot reconstruction (ordering+arbitration+M19 builder)"),
        ComponentInfo(ComponentKind.PROVIDER, "ops.snapshot_store", "1.0.0",
                      "Deterministic local sealed-snapshot store"),
    ):
        r.register(info)
    return r
