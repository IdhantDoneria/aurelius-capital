"""AIDP M20 — Live Market-Data, Replay & Production Data-Construction Layer.

The operational layer *above* M19 and feeding M18. M19 turns raw records into a PIT snapshot; M20
turns *sources* into an operable data lifecycle: adapter runtime with a capability model, an
immutable feed-message model, deterministic ordering/sequence policies, multi-source arbitration
and reconciliation, a replay engine, historical PIT reconstruction, a snapshot lifecycle + store,
incremental ingestion, operational quality/health/coverage monitoring, a fault-injecting streaming
simulator, and offline vendor contract boundaries.

Reuses M19 (normalization, quality, revisions, PIT builder, calibration) and M18 (the snapshot the
valuation engine consumes) unchanged; never forks the valuation, FX or risk engines. Fully offline
and deterministic — no paid market-data connectivity is claimed or required.

    from mentisrex.research import market_data_ops as ops
    eng = ops.MarketDataOperationsEngine(fx_provider=fx)
    eng.ingest(messages)
    rec = eng.reconstruct_snapshot(valuation_date=d, knowledge_date=d)
    snapshot = rec.snapshot            # an M18 MarketDataSnapshot, ready for the valuation engine
"""

from __future__ import annotations

from mentisrex.research.market_data_ops.adapters import (
    AdapterHealthSample,
    CapabilityError,
    ConnectionState,
    FixtureVendorAdapter,
    LocalSourceAdapter,
    MessageLogAdapter,
    ProductionSourceAdapter,
    SourceAdapter,
    SourceMetadata,
)
from mentisrex.research.market_data_ops.arbitration import (
    ArbitrationConfig,
    ArbitrationEvent,
    ArbitrationPolicy,
    ArbitrationResult,
    Disagreement,
    ReconciliationReport,
    SourceArbiter,
    reconcile,
)
from mentisrex.research.market_data_ops.engine import MarketDataOperationsEngine
from mentisrex.research.market_data_ops.incremental import (
    IngestReport,
    MarketDataState,
)
from mentisrex.research.market_data_ops.lifecycle import (
    SealedSnapshot,
    SnapshotState,
    reject,
    seal,
)
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
    message_from_observation,
)
from mentisrex.research.market_data_ops.monitoring import (
    CoverageReport,
    FeedHealth,
    FeedStatus,
    HealthMonitor,
    QualityHealthReport,
    QualityMonitor,
    coverage,
)
from mentisrex.research.market_data_ops.ordering import (
    OrderingCode,
    OrderingError,
    OrderingEvent,
    OrderingPolicy,
    OrderingReport,
    SequenceManager,
)
from mentisrex.research.market_data_ops.reconstruction import (
    HistoricalReconstructor,
    ReconstructionResult,
)
from mentisrex.research.market_data_ops.registry import (
    SnapshotLineage,
    default_ops_registry,
    lineage_of,
)
from mentisrex.research.market_data_ops.replay import (
    MarketDataReplayEngine,
    ReplayCheckpoint,
    ReplayConfig,
    ReplayResult,
)
from mentisrex.research.market_data_ops.serialization import (
    DeserializationError,
    message_from_dict,
    message_to_dict,
    messages_from_json,
    messages_to_json,
    sealed_to_dict,
    sealed_to_json,
)
from mentisrex.research.market_data_ops.simulator import (
    FaultSpec,
    SimConfig,
    StreamingSimulator,
)
from mentisrex.research.market_data_ops.store import (
    IntegrityError,
    SnapshotStore,
    SnapshotStoreError,
)

__version__ = "1.0.0"

__all__ = [
    "AdapterHealthSample",
    "ArbitrationConfig",
    "ArbitrationEvent",
    "ArbitrationPolicy",
    "ArbitrationResult",
    "CapabilityError",
    "ConnectionState",
    "CoverageReport",
    "DeserializationError",
    "Disagreement",
    "FaultSpec",
    "FeedHealth",
    "FeedStatus",
    "FixtureVendorAdapter",
    # monitoring
    "HealthMonitor",
    "HistoricalReconstructor",
    "IngestReport",
    "IntegrityError",
    "LocalSourceAdapter",
    "MarketDataOperationsEngine",
    # replay / reconstruction
    "MarketDataReplayEngine",
    "MarketDataState",
    "MessageLogAdapter",
    "MessageType",
    "OrderingCode",
    "OrderingError",
    "OrderingEvent",
    "OrderingPolicy",
    "OrderingReport",
    "ProductionSourceAdapter",
    "QualityHealthReport",
    "QualityMonitor",
    "ReconciliationReport",
    "ReconstructionResult",
    "ReplayCheckpoint",
    "ReplayConfig",
    "ReplayResult",
    # lifecycle / store / incremental
    "SealedSnapshot",
    # ordering
    "SequenceManager",
    "SimConfig",
    "SnapshotLineage",
    "SnapshotState",
    "SnapshotStore",
    "SnapshotStoreError",
    # adapters
    "SourceAdapter",
    # arbitration / reconciliation
    "SourceArbiter",
    "SourceCapability",
    # messages
    "SourceMessage",
    "SourceMetadata",
    # simulator
    "StreamingSimulator",
    "coverage",
    "default_ops_registry",
    "lineage_of",
    "message_from_dict",
    "message_from_observation",
    # serialization / registry
    "message_to_dict",
    "messages_from_json",
    "messages_to_json",
    "reconcile",
    "reject",
    "seal",
    "sealed_to_dict",
    "sealed_to_json",
]
