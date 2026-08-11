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

    from aurelius.research import market_data_ops as ops
    eng = ops.MarketDataOperationsEngine(fx_provider=fx)
    eng.ingest(messages)
    rec = eng.reconstruct_snapshot(valuation_date=d, knowledge_date=d)
    snapshot = rec.snapshot            # an M18 MarketDataSnapshot, ready for the valuation engine
"""

from __future__ import annotations

from aurelius.research.market_data_ops.adapters import (
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
from aurelius.research.market_data_ops.arbitration import (
    ArbitrationConfig,
    ArbitrationEvent,
    ArbitrationPolicy,
    ArbitrationResult,
    Disagreement,
    ReconciliationReport,
    SourceArbiter,
    reconcile,
)
from aurelius.research.market_data_ops.engine import MarketDataOperationsEngine
from aurelius.research.market_data_ops.incremental import (
    IngestReport,
    MarketDataState,
)
from aurelius.research.market_data_ops.lifecycle import (
    SealedSnapshot,
    SnapshotState,
    reject,
    seal,
)
from aurelius.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
    message_from_observation,
)
from aurelius.research.market_data_ops.monitoring import (
    CoverageReport,
    FeedHealth,
    FeedStatus,
    HealthMonitor,
    QualityHealthReport,
    QualityMonitor,
    coverage,
)
from aurelius.research.market_data_ops.ordering import (
    OrderingCode,
    OrderingEvent,
    OrderingError,
    OrderingPolicy,
    OrderingReport,
    SequenceManager,
)
from aurelius.research.market_data_ops.reconstruction import (
    HistoricalReconstructor,
    ReconstructionResult,
)
from aurelius.research.market_data_ops.registry import (
    SnapshotLineage,
    default_ops_registry,
    lineage_of,
)
from aurelius.research.market_data_ops.replay import (
    MarketDataReplayEngine,
    ReplayCheckpoint,
    ReplayConfig,
    ReplayResult,
)
from aurelius.research.market_data_ops.serialization import (
    DeserializationError,
    message_from_dict,
    message_to_dict,
    messages_from_json,
    messages_to_json,
    sealed_to_dict,
    sealed_to_json,
)
from aurelius.research.market_data_ops.simulator import (
    FaultSpec,
    SimConfig,
    StreamingSimulator,
)
from aurelius.research.market_data_ops.store import (
    IntegrityError,
    SnapshotStore,
    SnapshotStoreError,
)

__version__ = "1.0.0"

__all__ = [
    "MarketDataOperationsEngine",
    # messages
    "SourceMessage", "MessageType", "SourceCapability", "message_from_observation",
    # adapters
    "SourceAdapter", "SourceMetadata", "ConnectionState", "AdapterHealthSample", "CapabilityError",
    "LocalSourceAdapter", "MessageLogAdapter", "FixtureVendorAdapter", "ProductionSourceAdapter",
    # ordering
    "SequenceManager", "OrderingPolicy", "OrderingReport", "OrderingEvent", "OrderingCode",
    "OrderingError",
    # arbitration / reconciliation
    "SourceArbiter", "ArbitrationConfig", "ArbitrationPolicy", "ArbitrationResult",
    "ArbitrationEvent", "reconcile", "ReconciliationReport", "Disagreement",
    # replay / reconstruction
    "MarketDataReplayEngine", "ReplayConfig", "ReplayResult", "ReplayCheckpoint",
    "HistoricalReconstructor", "ReconstructionResult",
    # lifecycle / store / incremental
    "SealedSnapshot", "SnapshotState", "seal", "reject",
    "SnapshotStore", "SnapshotStoreError", "IntegrityError",
    "MarketDataState", "IngestReport",
    # monitoring
    "HealthMonitor", "FeedHealth", "FeedStatus", "coverage", "CoverageReport",
    "QualityMonitor", "QualityHealthReport",
    # simulator
    "StreamingSimulator", "SimConfig", "FaultSpec",
    # serialization / registry
    "message_to_dict", "message_from_dict", "messages_to_json", "messages_from_json",
    "sealed_to_dict", "sealed_to_json", "DeserializationError",
    "default_ops_registry", "SnapshotLineage", "lineage_of",
]
