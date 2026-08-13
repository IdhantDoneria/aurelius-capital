"""Historical point-in-time reconstruction (AIDP M20).

The single most important deliverable of M20: given a valuation date and a **knowledge boundary**,
rebuild the exact immutable market state Mentisrex would have known — nothing knowable only after
the boundary may enter it. This is what makes a backtest honest.

The reconstruction is a pure function of the message multiset and the two dates. It composes
existing pieces rather than reinventing them:

    admissibility filter (knowledge ≤ boundary, observation ≤ valuation)
      → M20 ordering (dedup, canonical order)
      → M20 arbitration (one winner per observation key, per policy)
      → M19 Normalizer + QualityEngine + MarketDataSnapshotBuilder → M18 MarketDataSnapshot

An M19 `RevisionStore` is built in parallel over the admissible numeric messages so the bitemporal
audit trail (`history` / `was_restated` / `known_as_of`) survives every reconstruction. Because the
result depends only on the admissible *set*, incremental ingestion equals full rebuild, and replay
equals direct reconstruction (both proven in the tests).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from mentisrex.research.market_data.models import ObservationType
from mentisrex.research.market_data.normalization import Normalizer
from mentisrex.research.market_data.pit import (
    MarketDataSnapshotBuilder,
    PITPolicy,
)
from mentisrex.research.market_data.quality import MarketDataQualityEngine
from mentisrex.research.market_data.revisions import RevisionStore
from mentisrex.research.market_data_ops.arbitration import (
    ArbitrationConfig,
    ArbitrationResult,
    SourceArbiter,
)
from mentisrex.research.market_data_ops.messages import MessageType, SourceMessage
from mentisrex.research.market_data_ops.ordering import (
    OrderingPolicy,
    OrderingReport,
    SequenceManager,
)


@dataclass(frozen=True)
class ReconstructionResult:
    snapshot: object                     # M18 MarketDataSnapshot
    valuation_date: date
    knowledge_date: date
    fingerprint: str
    winners: tuple = ()                  # the SourceMessages that became state
    revision_store: RevisionStore | None = None
    ordering_report: OrderingReport | None = None
    arbitration: ArbitrationResult | None = None
    diagnostics: tuple = ()

    def known_as_of(self, security_id: str, obs_type: str, field: str, effective_date: date):
        """Bitemporal audit lookup — the value knowable at this reconstruction's boundary."""
        if self.revision_store is None:
            return None
        return self.revision_store.known_as_of(security_id, f"{obs_type}:{field}",
                                               effective_date, self.knowledge_date)


class HistoricalReconstructor:
    """Reconstructs a PIT `MarketDataSnapshot` from a message log. Ordering + arbitration policies
    and the M19 normalizer/quality engine are dependency-injected; nothing is assumed."""

    def __init__(self, *, normalizer: Normalizer | None = None,
                 quality: MarketDataQualityEngine | None = None,
                 ordering: SequenceManager | None = None,
                 arbiter: SourceArbiter | None = None) -> None:
        self.normalizer = normalizer or Normalizer()
        self.quality = quality or MarketDataQualityEngine()
        self.ordering = ordering or SequenceManager(OrderingPolicy.REORDER)
        self.arbiter = arbiter or SourceArbiter(ArbitrationConfig())

    def reconstruct(self, messages, *, valuation_date: date, knowledge_date: date | None = None,
                    curves=None, discount_curves=None, vol_surfaces=None, dividend_yields=None,
                    forwards=None, fx_provider=None, corporate_actions=None,
                    security_ids=None, fields=None,
                    policy: PITPolicy | None = None) -> ReconstructionResult:
        knowledge_date = knowledge_date or valuation_date

        # 1. admissibility — the PIT gate. Nothing knowable after the boundary; nothing observed
        #    after the valuation date. This is what forbids look-ahead structurally.
        admissible = [m for m in messages if _admissible(m, valuation_date, knowledge_date,
                                                          security_ids, fields)]

        # 2. deterministic ordering (dedup + canonical order)
        ordering_report = self.ordering.process(admissible)
        ordered = list(ordering_report.accepted)

        # 3. arbitration — one winner per (security, field, effective_date), per policy
        arb = self.arbiter.arbitrate([m for m in ordered
                                      if m.msg_type is not MessageType.TOMBSTONE])
        winners = list(arb.winners)

        # tombstones remove any winner they cover
        tombstoned = {(_k(m)) for m in ordered if m.msg_type is MessageType.TOMBSTONE}
        winners = [w for w in winners if _k(w) not in tombstoned]

        # 4. bitemporal audit store over admissible numeric messages
        store = self._build_revision_store(ordered)

        # 5. M19 pipeline → M18 snapshot (reuses normalize → quality → PIT → assemble)
        builder = MarketDataSnapshotBuilder(normalizer=self.normalizer, quality=self.quality)
        raw = [dict(w.payload) for w in winners]
        build = builder.build(as_of=valuation_date, raw=raw, curves=curves,
                              discount_curves=discount_curves, vol_surfaces=vol_surfaces,
                              dividend_yields=dividend_yields, forwards=forwards,
                              fx_provider=fx_provider, corporate_actions=corporate_actions,
                              policy=policy)

        fp = _reconstruction_fingerprint(valuation_date, knowledge_date, winners,
                                         build.snapshot, arb.policy_fingerprint)
        diags = tuple(build.diagnostics)
        return ReconstructionResult(build.snapshot, valuation_date, knowledge_date, fp,
                                    tuple(winners), store, ordering_report, arb, diags)

    def _build_revision_store(self, messages) -> RevisionStore:
        store = RevisionStore()
        # feed in knowledge-date order so revision numbers are monotone in publication time
        for m in sorted(messages, key=lambda x: (x.knowledge_date or date.min,
                                                  -1 if x.sequence is None else x.sequence)):
            sec, fld, eff = m.security_hint, m.field_hint, m.effective_date
            val = m.payload.get("value") if isinstance(m.payload, dict) else None
            if sec is None or fld is None or eff is None or val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            otype = _obs_type_hint(m)
            store.record(sec, f"{otype}:{fld}", eff, fval,
                         knowledge_date=m.knowledge_date or eff, source=m.source)
        return store


# ── helpers ────────────────────────────────────────────────────────────────────

def _admissible(m: SourceMessage, valuation_date, knowledge_date, security_ids, fields) -> bool:
    if m.msg_type in (MessageType.HEARTBEAT, MessageType.STATUS):
        return False
    kd = m.knowledge_date
    if kd is not None and kd > knowledge_date:
        return False
    if m.observation_date is not None and m.observation_date > valuation_date:
        return False
    if m.effective_date is not None and m.effective_date > valuation_date:
        return False
    if security_ids is not None and m.security_hint not in set(map(str, security_ids)):
        return False
    if fields is not None and m.field_hint not in set(fields):
        return False
    return True


def _k(m: SourceMessage) -> tuple:
    return (m.security_hint, m.field_hint, m.effective_date)


def _obs_type_hint(m: SourceMessage) -> str:
    p = m.payload if isinstance(m.payload, dict) else {}
    t = str(p.get("type", "")).lower()
    for ot in ObservationType:
        if ot.value == t:
            return ot.value
    return "observation"


def _reconstruction_fingerprint(vd, kd, winners, snapshot, policy_fp) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(f"vd={vd}|kd={kd}|arb={policy_fp}".encode())
    for fp in sorted(w.raw_fingerprint() for w in winners):
        h.update(fp.encode())
    h.update(f"snap={snapshot.fingerprint()}".encode())
    return h.hexdigest()
