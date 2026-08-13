"""Market-data operations engine — façade (AIDP M20).

One entry point that wires the operational pipeline: adapters → ingest → ordering → arbitration →
PIT reconstruction → seal → store, plus health/coverage monitoring and replay. Everything it
composes is dependency-injected and already tested in isolation; the façade adds no new market-data
logic, it just orchestrates.

The research-facing method is `reconstruct_snapshot(valuation_date, knowledge_date, ...)` — the M18
snapshot it returns is consumed by the valuation engine with no special handling.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.market_data_ops.arbitration import ArbitrationConfig, SourceArbiter
from mentisrex.research.market_data_ops.incremental import IngestReport, MarketDataState
from mentisrex.research.market_data_ops.lifecycle import SealedSnapshot, seal
from mentisrex.research.market_data_ops.monitoring import (
    CoverageReport,
    HealthMonitor,
    QualityMonitor,
    coverage,
)
from mentisrex.research.market_data_ops.ordering import OrderingPolicy, SequenceManager
from mentisrex.research.market_data_ops.reconstruction import (
    HistoricalReconstructor,
    ReconstructionResult,
)
from mentisrex.research.market_data_ops.registry import SnapshotLineage, lineage_of
from mentisrex.research.market_data_ops.replay import (
    MarketDataReplayEngine,
    ReplayConfig,
    ReplayResult,
)
from mentisrex.research.market_data_ops.store import SnapshotStore


class MarketDataOperationsEngine:
    def __init__(self, *, adapters=None, reconstructor: HistoricalReconstructor | None = None,
                 ordering: SequenceManager | None = None, arbiter: SourceArbiter | None = None,
                 store: SnapshotStore | None = None, fx_provider=None) -> None:
        self.reconstructor = reconstructor or HistoricalReconstructor(
            ordering=ordering or SequenceManager(OrderingPolicy.REORDER),
            arbiter=arbiter or SourceArbiter(ArbitrationConfig()))
        self.store = store or SnapshotStore()
        self.fx_provider = fx_provider
        self.adapters = list(adapters or [])
        self._state = MarketDataState(reconstructor=self.reconstructor)

    # ── ingestion ────────────────────────────────────────────────────────────────
    def add_adapter(self, adapter) -> None:
        self.adapters.append(adapter)

    def ingest(self, messages) -> IngestReport:
        return self._state.ingest(messages)

    def ingest_from_adapters(self, as_of: date, *, security_ids=None, fields=None) -> IngestReport:
        collected: list = []
        for a in self.adapters:
            collected.extend(a.fetch(as_of, security_ids=security_ids, fields=fields))
        return self._state.ingest(collected)

    @property
    def messages(self) -> tuple:
        return self._state.messages

    def state_fingerprint(self) -> str:
        return self._state.fingerprint()

    # ── reconstruction (research API §4.18) ──────────────────────────────────────
    def reconstruct_snapshot(self, *, valuation_date: date, knowledge_date: date | None = None,
                             curves=None, discount_curves=None, vol_surfaces=None,
                             dividend_yields=None, forwards=None, corporate_actions=None,
                             security_ids=None, fields=None) -> ReconstructionResult:
        return self._state.reconstruct(
            valuation_date=valuation_date, knowledge_date=knowledge_date, curves=curves,
            discount_curves=discount_curves, vol_surfaces=vol_surfaces,
            dividend_yields=dividend_yields, forwards=forwards, corporate_actions=corporate_actions,
            fx_provider=self.fx_provider, security_ids=security_ids, fields=fields)

    def build_and_seal(self, *, valuation_date: date, knowledge_date: date | None = None,
                       store: bool = True, versions: dict | None = None, **kwargs) -> SealedSnapshot:
        rec = self.reconstruct_snapshot(valuation_date=valuation_date,
                                        knowledge_date=knowledge_date, **kwargs)
        sealed = seal(rec, versions=versions)
        if store:
            self.store.put(sealed)
        return sealed

    def lineage(self, sealed: SealedSnapshot) -> SnapshotLineage:
        arb_fp = sealed.reconstruction_fingerprint  # arbitration fp folded into reconstruction fp
        return lineage_of(sealed, arbitration_fingerprint=arb_fp)

    # ── replay ───────────────────────────────────────────────────────────────────
    def replay(self, config: ReplayConfig | None = None, *, reconstruct: bool = True,
               **kwargs) -> ReplayResult:
        engine = MarketDataReplayEngine(self._state.messages, reconstructor=self.reconstructor)
        return engine.replay(config, reconstruct=reconstruct, fx_provider=self.fx_provider, **kwargs)

    # ── monitoring ───────────────────────────────────────────────────────────────
    def health(self, *, as_of: date, stale_after_days: int = 3, disconnected_sources=None) -> dict:
        ordering = self.reconstructor.ordering.process(self._state.messages)
        return HealthMonitor(stale_after_days=stale_after_days).assess(
            self._state.messages, as_of=as_of, ordering=ordering,
            disconnected_sources=disconnected_sources)

    def quality_health(self, *, as_of: date):
        return QualityMonitor().monitor(self._state.messages, as_of=as_of)

    def coverage(self, *, expected_securities=None, expected_fields=None,
                 expected_dates=None) -> CoverageReport:
        return coverage(self._state.messages, expected_securities=expected_securities,
                        expected_fields=expected_fields, expected_dates=expected_dates)
