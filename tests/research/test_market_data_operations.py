"""AIDP M20 — market-data operations tests (deterministic, offline).

Every test is deterministic and offline: no network, no wall-clock, no unseeded RNG. Covers the
feed-message model, adapter runtime + capabilities, ordering/sequence policies, arbitration &
reconciliation, replay, PIT reconstruction, snapshot lifecycle/store, incremental ingestion,
monitoring (health/coverage/quality), the fault-injecting simulator, serialization, offline vendor
contracts, M18/M19 integration, registry/lineage, determinism and financial/data invariants, plus
adversarial fault cases.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

import aurelius.research.fx as m16fx
import aurelius.research.instruments as ins
from aurelius.research import market_data as md
from aurelius.research import market_data_ops as ops
from aurelius.research.market_data.sabr import sabr_vol
from aurelius.research.valuation.engine import PortfolioValuationEngine, ValuationEngine
from aurelius.research.valuation.models import ValuationConfiguration

REF = date(2024, 6, 3)


# ── helpers ─────────────────────────────────────────────────────────────────────

def obsmsg(sid, field, value, obs, *, eff=None, source="v", seq=None, ts=None,
           mtype=ops.MessageType.OBSERVATION, revision=0, currency="USD", otype="close"):
    payload = {"id": sid, "id_type": "ticker", "field": field, "type": otype, "value": value,
               "currency": currency, "unit": "price", "source": source, "revision": revision,
               "observation_date": obs.isoformat(), "effective_date": (eff or obs).isoformat()}
    return ops.SourceMessage(source=source, payload=payload, msg_type=mtype, vendor_id=sid,
                             sequence=seq, source_timestamp=ts, observation_date=obs,
                             effective_date=eff or obs)


def sim(seeds=None, *, days=5, start=date(2024, 6, 1), seed=0):
    return ops.StreamingSimulator(ops.SimConfig(
        seeds=seeds or {"AAPL": 190.0, "MSFT": 400.0}, start=start, days=days, seed=seed))


def calibrated_curve():
    return md.CurveBootstrapper().bootstrap(
        [md.deposit(0.25, 0.05), md.swap(1, 0.05), md.swap(5, 0.05), md.swap(10, 0.05)],
        REF, curve_id="USD").curve


def calibrated_surface(f=190.0):
    def smile(t):
        ks = tuple(f * m for m in (0.8, 0.9, 1.0, 1.1, 1.2))
        return md.SmileQuotes(f, t, ks, tuple(sabr_vol(f, k, t, 0.25, 0.5, -0.3, 0.4) for k in ks),
                              underlying="AAPL")
    return md.VolatilitySurfaceCalibrator(md.VolModel.SVI).calibrate_surface(
        [smile(t) for t in (0.5, 1.0, 2.0)], "AAPL", REF)[0]


def integ_snapshot():
    fx = m16fx.rates.StaticFXRateProvider({"EUR/USD": 1.10})
    eng = ops.MarketDataOperationsEngine(fx_provider=fx)
    eng.ingest([obsmsg("AAPL", "close", 190.0, date(2024, 6, 2))])
    return eng.reconstruct_snapshot(
        valuation_date=REF, knowledge_date=REF, curves={"USD": calibrated_curve()},
        vol_surfaces={"AAPL": calibrated_surface()}, dividend_yields={"AAPL": 0.005}).snapshot


# ══════════════════════════════════════════════════════════════════════════════
# 1. Feed-message model
# ══════════════════════════════════════════════════════════════════════════════

def test_message_fingerprint_stable():
    m = obsmsg("AAPL", "close", 190.0, REF)
    assert m.raw_fingerprint() == m.raw_fingerprint()


def test_message_fingerprint_differs_on_value():
    a = obsmsg("AAPL", "close", 190.0, REF)
    b = obsmsg("AAPL", "close", 191.0, REF)
    assert a.raw_fingerprint() != b.raw_fingerprint()


def test_message_knowledge_date_prefers_source_timestamp():
    m = obsmsg("AAPL", "close", 190.0, date(2024, 6, 2), ts=datetime(2024, 6, 5, 16))
    assert m.knowledge_date == date(2024, 6, 5)


def test_message_knowledge_date_falls_back_to_observation():
    m = obsmsg("AAPL", "close", 190.0, date(2024, 6, 2))
    assert m.knowledge_date == date(2024, 6, 2)


def test_message_infers_dates_from_payload():
    m = ops.SourceMessage(source="v", payload={"id": "X", "field": "close", "value": 1.0,
                                               "observation_date": "2024-06-03"})
    assert m.observation_date == REF and m.effective_date == REF


def test_message_security_and_field_hints():
    m = obsmsg("AAPL", "bid", 189.0, REF)
    assert m.security_hint == "AAPL" and m.field_hint == "bid"


def test_message_from_observation_roundtrips_key():
    o = md.CanonicalObservation("AAPL", md.ObservationType.CLOSE, "close", 190.0, REF, REF)
    m = ops.message_from_observation(o, source="v")
    assert m.security_hint == "AAPL" and float(m.payload["value"]) == 190.0


def test_message_types_distinct():
    assert ops.MessageType.TOMBSTONE != ops.MessageType.OBSERVATION


def test_message_with_receive_timestamp_immutable():
    m = obsmsg("AAPL", "close", 190.0, REF)
    m2 = m.with_receive_timestamp(datetime(2024, 6, 3, 17))
    assert m.receive_timestamp is None and m2.receive_timestamp is not None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Adapter runtime + capabilities
# ══════════════════════════════════════════════════════════════════════════════

def test_local_adapter_wraps_m19_source():
    src = md.StaticSource([{"id": "AAPL", "field": "close", "value": 190.0,
                            "observation_date": "2024-06-02"}])
    a = ops.LocalSourceAdapter(src, capabilities=(ops.SourceCapability.HISTORICAL,))
    msgs = a.fetch(REF)
    assert len(msgs) == 1 and msgs[0].security_hint == "AAPL"


def test_adapter_capability_declared_and_checked():
    a = ops.LocalSourceAdapter(md.StaticSource([]), capabilities=(ops.SourceCapability.HISTORICAL,))
    assert a.supports(ops.SourceCapability.HISTORICAL)
    assert not a.supports(ops.SourceCapability.STREAMING)


def test_adapter_require_raises_on_missing_capability():
    a = ops.LocalSourceAdapter(md.StaticSource([]), capabilities=(ops.SourceCapability.HISTORICAL,))
    with pytest.raises(ops.CapabilityError):
        a.require(ops.SourceCapability.OPTIONS)


def test_adapter_lifecycle_state():
    a = ops.LocalSourceAdapter(md.StaticSource([]))
    assert a.state is ops.ConnectionState.DISCONNECTED
    a.connect()
    assert a.state is ops.ConnectionState.CONNECTED
    a.disconnect()
    assert a.state is ops.ConnectionState.DISCONNECTED


def test_adapter_subscription_filters_health():
    src = md.StaticSource([{"id": "AAPL", "field": "close", "value": 1.0, "observation_date": "2024-06-02"},
                           {"id": "MSFT", "field": "close", "value": 2.0, "observation_date": "2024-06-02"}])
    a = ops.LocalSourceAdapter(src)
    a.subscribe(["AAPL"])
    msgs = a.fetch(REF)
    assert {m.security_hint for m in msgs} == {"AAPL"}
    assert a.subscriptions == ("AAPL",)


def test_message_log_adapter_fetch_pit():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 1)),
            obsmsg("A", "close", 2.0, date(2024, 6, 5))]
    a = ops.MessageLogAdapter(msgs)
    assert len(a.fetch(date(2024, 6, 2))) == 1


def test_message_log_adapter_poll_streams():
    msgs = [obsmsg("A", "close", float(i), date(2024, 6, 1), seq=i) for i in range(5)]
    a = ops.MessageLogAdapter(msgs)
    first = a.poll(max_messages=2)
    second = a.poll(max_messages=2)
    assert len(first) == 2 and len(second) == 2 and first[0] is not second[0]


def test_message_log_adapter_reset():
    a = ops.MessageLogAdapter([obsmsg("A", "close", 1.0, REF, seq=1)])
    a.poll()
    a.reset()
    assert len(a.poll()) == 1


def test_fixture_vendor_adapter_labels_vendor():
    a = ops.FixtureVendorAdapter("bloomberg", [obsmsg("A", "close", 1.0, REF)])
    assert a.metadata.vendor == "bloomberg" and "bloomberg" in a.metadata.name


def test_production_adapter_connect_raises_with_unblock():
    a = ops.ProductionSourceAdapter("live", (ops.SourceCapability.STREAMING,))
    with pytest.raises(NotImplementedError) as e:
        a.connect()
    assert "Unblock" in str(e.value)


def test_production_adapter_fetch_raises():
    a = ops.ProductionSourceAdapter("live", (ops.SourceCapability.HISTORICAL,))
    with pytest.raises(NotImplementedError):
        a.fetch(REF)


def test_adapter_health_tracks_counts():
    a = ops.LocalSourceAdapter(md.DeterministicMockSource({"A": 100.0}))
    a.fetch(REF)
    h = a.health()
    assert h.message_count == 1 and h.state is ops.ConnectionState.CONNECTED


# ══════════════════════════════════════════════════════════════════════════════
# 3. Ordering & sequence management
# ══════════════════════════════════════════════════════════════════════════════

def test_ordering_dedup_by_fingerprint():
    m = obsmsg("A", "close", 1.0, REF, seq=1)
    rep = ops.SequenceManager(ops.OrderingPolicy.REORDER).process([m, m, m])
    assert len(rep.accepted) == 1
    assert rep.event_counts.get("duplicate", 0) == 2


def test_ordering_reorder_is_canonical():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1, ts=datetime(2024, 6, 1, 16))
    b = obsmsg("A", "close", 2.0, date(2024, 6, 2), seq=2, ts=datetime(2024, 6, 2, 16))
    fwd = ops.SequenceManager().process([a, b]).accepted
    rev = ops.SequenceManager().process([b, a]).accepted
    assert [m.raw_fingerprint() for m in fwd] == [m.raw_fingerprint() for m in rev]


def test_ordering_detects_out_of_order():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1, ts=datetime(2024, 6, 1, 16))
    b = obsmsg("A", "close", 2.0, date(2024, 6, 2), seq=2, ts=datetime(2024, 6, 2, 16))
    rep = ops.SequenceManager(ops.OrderingPolicy.BUFFER).process([b, a])
    assert rep.event_counts.get("out_of_order", 0) >= 1


def test_ordering_detects_sequence_gap():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1)
    c = obsmsg("A", "close", 3.0, date(2024, 6, 3), seq=5)
    rep = ops.SequenceManager().process([a, c])
    assert rep.event_counts.get("sequence_gap", 0) >= 1


def test_ordering_detects_duplicate_sequence():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1)
    b = obsmsg("A", "close", 2.0, date(2024, 6, 2), seq=1)
    rep = ops.SequenceManager().process([a, b])
    assert rep.event_counts.get("duplicate_sequence", 0) >= 1


def test_ordering_missing_sequence_flagged():
    a = obsmsg("A", "close", 1.0, REF, seq=None)
    rep = ops.SequenceManager().process([a])
    assert rep.event_counts.get("missing_sequence", 0) == 1


def test_ordering_stale_boundary():
    old = obsmsg("A", "close", 1.0, date(2024, 5, 1))
    rep = ops.SequenceManager(stale_boundary=date(2024, 6, 1)).process([old])
    assert rep.event_counts.get("stale", 0) == 1


def test_ordering_strict_raises_on_out_of_order():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1, ts=datetime(2024, 6, 1, 16))
    b = obsmsg("A", "close", 2.0, date(2024, 6, 2), seq=2, ts=datetime(2024, 6, 2, 16))
    with pytest.raises(ops.OrderingError):
        ops.SequenceManager(ops.OrderingPolicy.STRICT).process([b, a])


def test_ordering_reject_drops_out_of_order():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1, ts=datetime(2024, 6, 1, 16))
    b = obsmsg("A", "close", 2.0, date(2024, 6, 2), seq=2, ts=datetime(2024, 6, 2, 16))
    rep = ops.SequenceManager(ops.OrderingPolicy.REJECT).process([b, a])
    assert len(rep.accepted) == 1 and len(rep.dropped) == 1


def test_ordering_quarantine_diverts():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1, ts=datetime(2024, 6, 1, 16))
    b = obsmsg("A", "close", 2.0, date(2024, 6, 2), seq=2, ts=datetime(2024, 6, 2, 16))
    rep = ops.SequenceManager(ops.OrderingPolicy.QUARANTINE).process([b, a])
    assert len(rep.quarantined) == 1


def test_ordering_latest_valid_keeps_newest_per_key():
    a = obsmsg("A", "close", 1.0, date(2024, 6, 1), eff=date(2024, 6, 1), seq=1,
               ts=datetime(2024, 6, 1, 16))
    b = obsmsg("A", "close", 2.0, date(2024, 6, 1), eff=date(2024, 6, 1), seq=2,
               ts=datetime(2024, 6, 2, 16))
    rep = ops.SequenceManager(ops.OrderingPolicy.LATEST_VALID).process([a, b])
    assert len(rep.accepted) == 1 and float(rep.accepted[0].payload["value"]) == 2.0


def test_ordering_buffer_keeps_all():
    msgs = [obsmsg("A", "close", float(i), date(2024, 6, 1) + timedelta(days=i), seq=i)
            for i in range(4)]
    rep = ops.SequenceManager(ops.OrderingPolicy.BUFFER).process(msgs)
    assert len(rep.accepted) == 4


def test_ordering_empty_batch():
    rep = ops.SequenceManager().process([])
    assert rep.accepted == () and rep.events == ()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Arbitration
# ══════════════════════════════════════════════════════════════════════════════

def _two_source(vA=100.0, vB=100.5):
    a = obsmsg("X", "close", vA, REF, source="A")
    b = obsmsg("X", "close", vB, REF, source="B")
    return [a, b]


def test_arbitration_source_priority():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.SOURCE_PRIORITY, priority=("B", "A"))
    res = ops.SourceArbiter(cfg).arbitrate(_two_source())
    assert len(res.winners) == 1 and res.winners[0].source == "B"


def test_arbitration_primary_source():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.PRIMARY_SOURCE, primary="A")
    res = ops.SourceArbiter(cfg).arbitrate(_two_source())
    assert res.winners[0].source == "A"


def test_arbitration_primary_missing_drops():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.PRIMARY_SOURCE, primary="Z")
    res = ops.SourceArbiter(cfg).arbitrate(_two_source())
    assert not res.winners and len(res.dropped) == 1


def test_arbitration_latest_valid():
    a = obsmsg("X", "close", 100.0, REF, source="A", ts=datetime(2024, 6, 3, 10))
    b = obsmsg("X", "close", 101.0, REF, source="B", ts=datetime(2024, 6, 3, 16))
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.LATEST_VALID)
    res = ops.SourceArbiter(cfg).arbitrate([a, b])
    assert float(res.winners[0].payload["value"]) == 101.0


def test_arbitration_cross_source_confirmation_pass():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.CROSS_SOURCE_CONFIRMATION,
                                tolerance_frac=1e-3, min_confirmations=2)
    res = ops.SourceArbiter(cfg).arbitrate(_two_source(100.0, 100.05))
    assert len(res.winners) == 1


def test_arbitration_cross_source_confirmation_insufficient():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.CROSS_SOURCE_CONFIRMATION,
                                tolerance_frac=1e-6, min_confirmations=2)
    res = ops.SourceArbiter(cfg).arbitrate(_two_source(100.0, 105.0))
    assert not res.winners


def test_arbitration_reject_on_conflict():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.REJECT_ON_CONFLICT, tolerance_frac=1e-6)
    res = ops.SourceArbiter(cfg).arbitrate(_two_source(100.0, 105.0))
    assert not res.winners and len(res.dropped) == 1


def test_arbitration_reject_on_conflict_agree_keeps():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.REJECT_ON_CONFLICT, tolerance_frac=1e-3)
    res = ops.SourceArbiter(cfg).arbitrate(_two_source(100.0, 100.05))
    assert len(res.winners) == 1


def test_arbitration_policy_fingerprint_stable():
    cfg = ops.ArbitrationConfig(ops.ArbitrationPolicy.SOURCE_PRIORITY, priority=("A", "B"))
    assert cfg.fingerprint() == ops.ArbitrationConfig(
        ops.ArbitrationPolicy.SOURCE_PRIORITY, priority=("A", "B")).fingerprint()


def test_arbitration_deterministic_key_order():
    msgs = _two_source() + [obsmsg("Y", "close", 5.0, REF, source="A")]
    r1 = ops.SourceArbiter().arbitrate(msgs)
    r2 = ops.SourceArbiter().arbitrate(list(reversed(msgs)))
    assert [w.security_hint for w in r1.winners] == [w.security_hint for w in r2.winners]


def test_arbitration_single_source_passthrough():
    res = ops.SourceArbiter().arbitrate([obsmsg("X", "close", 1.0, REF, source="A")])
    assert len(res.winners) == 1 and not res.events


# ══════════════════════════════════════════════════════════════════════════════
# 5. Cross-source reconciliation
# ══════════════════════════════════════════════════════════════════════════════

def test_reconcile_agreement():
    rep = ops.reconcile(_two_source(100.0, 100.0000001))
    assert rep.ok and rep.agreed_keys == 1


def test_reconcile_disagreement():
    rep = ops.reconcile(_two_source(100.0, 105.0))
    assert not rep.ok and rep.disagreements[0].kind == "value"


def test_reconcile_max_rel_diff():
    rep = ops.reconcile(_two_source(100.0, 110.0))
    assert abs(rep.disagreements[0].max_rel_diff - 10.0 / 110.0) < 1e-9


def test_reconcile_single_source_no_disagreement():
    rep = ops.reconcile([obsmsg("X", "close", 1.0, REF, source="A")])
    assert rep.ok


# ══════════════════════════════════════════════════════════════════════════════
# 6. Replay engine
# ══════════════════════════════════════════════════════════════════════════════

def test_replay_deterministic_fingerprint():
    msgs = sim(days=4).generate(ops.FaultSpec())
    e1 = ops.MarketDataReplayEngine(msgs).replay(reconstruct=False)
    e2 = ops.MarketDataReplayEngine(list(reversed(msgs))).replay(reconstruct=False)
    assert e1.replay_fingerprint == e2.replay_fingerprint


def test_replay_checkpoints_monotone_emitted():
    msgs = sim(days=4).generate(ops.FaultSpec())
    res = ops.MarketDataReplayEngine(msgs).replay(reconstruct=False)
    emitted = [c.emitted for c in res.checkpoints]
    assert emitted == sorted(emitted)


def test_replay_equals_direct_reconstruction():
    msgs = sim(days=5).generate(ops.FaultSpec(revision_frac=0.3, duplicate_frac=0.2))
    vd = date(2024, 6, 5)
    res = ops.MarketDataReplayEngine(msgs).replay(ops.ReplayConfig(dates=(vd,)))
    direct = ops.HistoricalReconstructor().reconstruct(msgs, valuation_date=vd, knowledge_date=vd)
    assert res.snapshot_on(vd).fingerprint() == direct.snapshot.fingerprint()


def test_replay_date_range_filter():
    msgs = sim(days=6).generate(ops.FaultSpec())
    res = ops.MarketDataReplayEngine(msgs).replay(
        ops.ReplayConfig(start=date(2024, 6, 3), end=date(2024, 6, 5)), reconstruct=False)
    assert all(date(2024, 6, 3) <= c.valuation_date <= date(2024, 6, 5) for c in res.checkpoints)


def test_replay_security_filter():
    msgs = sim({"A": 1.0, "B": 2.0}, days=3).generate(ops.FaultSpec())
    res = ops.MarketDataReplayEngine(msgs).replay(
        ops.ReplayConfig(security_ids=("A",)), reconstruct=True)
    snap = res.checkpoints[-1].reconstruction.snapshot
    assert "A" in snap.spots and "B" not in snap.spots


def test_replay_knowledge_lag():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 1), seq=1)]
    res = ops.MarketDataReplayEngine(msgs).replay(
        ops.ReplayConfig(dates=(date(2024, 6, 1),), knowledge_lag_days=2), reconstruct=True)
    assert res.checkpoints[0].knowledge_date == date(2024, 6, 3)


def test_replay_explicit_dates():
    msgs = sim(days=5).generate(ops.FaultSpec())
    res = ops.MarketDataReplayEngine(msgs).replay(
        ops.ReplayConfig(dates=(date(2024, 6, 2), date(2024, 6, 4))), reconstruct=False)
    assert [c.valuation_date for c in res.checkpoints] == [date(2024, 6, 2), date(2024, 6, 4)]


def test_replay_empty_log():
    res = ops.MarketDataReplayEngine([]).replay()
    assert res.checkpoints == () and res.total_emitted == 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. Historical PIT reconstruction (adversarial)
# ══════════════════════════════════════════════════════════════════════════════

def test_pit_excludes_observation_after_valuation_date():
    msgs = [obsmsg("A", "close", 100.0, date(2024, 6, 2)),
            obsmsg("A", "close", 200.0, date(2024, 6, 10))]
    rec = ops.HistoricalReconstructor().reconstruct(msgs, valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots["A"] == 100.0


def test_pit_excludes_revision_known_after_boundary():
    m0 = obsmsg("A", "close", 100.0, date(2024, 6, 3), ts=datetime(2024, 6, 3, 16))
    m1 = obsmsg("A", "close", 150.0, date(2024, 6, 3), revision=1,
                mtype=ops.MessageType.REVISION, ts=datetime(2024, 6, 6, 16))
    rec = ops.HistoricalReconstructor().reconstruct(
        [m0, m1], valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots["A"] == 100.0


def test_pit_includes_revision_after_knowledge_advances():
    m0 = obsmsg("A", "close", 100.0, date(2024, 6, 3), ts=datetime(2024, 6, 3, 16))
    m1 = obsmsg("A", "close", 150.0, date(2024, 6, 3), revision=1,
                mtype=ops.MessageType.REVISION, ts=datetime(2024, 6, 6, 16))
    rec = ops.HistoricalReconstructor().reconstruct(
        [m0, m1], valuation_date=REF, knowledge_date=date(2024, 6, 6))
    assert rec.snapshot.spots["A"] == 150.0


def test_pit_late_quote_does_not_leak():
    late = obsmsg("A", "close", 999.0, date(2024, 6, 2), ts=datetime(2024, 6, 9, 16))
    good = obsmsg("A", "close", 100.0, date(2024, 6, 2), ts=datetime(2024, 6, 2, 16))
    rec = ops.HistoricalReconstructor().reconstruct([good, late], valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots["A"] == 100.0


def test_pit_tombstone_removes_observation():
    st = ops.MarketDataState()
    st.ingest([obsmsg("A", "close", 100.0, date(2024, 6, 2))])
    st.tombstone(security_id="A", field="close", effective_date=date(2024, 6, 2))
    rec = st.reconstruct(valuation_date=REF, knowledge_date=REF)
    assert "A" not in rec.snapshot.spots


def test_pit_known_as_of_audit_trail():
    m0 = obsmsg("A", "close", 100.0, date(2024, 6, 3), ts=datetime(2024, 6, 3, 16))
    m1 = obsmsg("A", "close", 150.0, date(2024, 6, 3), revision=1,
                mtype=ops.MessageType.REVISION, ts=datetime(2024, 6, 6, 16))
    rec = ops.HistoricalReconstructor().reconstruct(
        [m0, m1], valuation_date=REF, knowledge_date=date(2024, 6, 6))
    rr = rec.known_as_of("A", "close", "close", date(2024, 6, 3))
    assert rr is not None and rr.value == 150.0


def test_pit_revision_store_was_restated():
    m0 = obsmsg("A", "close", 100.0, date(2024, 6, 3), ts=datetime(2024, 6, 3, 16))
    m1 = obsmsg("A", "close", 150.0, date(2024, 6, 3), revision=1,
                mtype=ops.MessageType.REVISION, ts=datetime(2024, 6, 6, 16))
    rec = ops.HistoricalReconstructor().reconstruct(
        [m0, m1], valuation_date=REF, knowledge_date=date(2024, 6, 6))
    assert rec.revision_store.was_restated("A", "close:close", date(2024, 6, 3))


def test_pit_corrected_fx_fixing_selects_knowable():
    a = obsmsg("EURUSD", "close", 1.10, date(2024, 6, 3), source="v", ts=datetime(2024, 6, 3, 16))
    b = obsmsg("EURUSD", "close", 1.20, date(2024, 6, 3), source="v", revision=1,
               mtype=ops.MessageType.REVISION, ts=datetime(2024, 6, 7, 16))
    rec = ops.HistoricalReconstructor().reconstruct([a, b], valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots["EURUSD"] == 1.10


def test_pit_reconstruction_fingerprint_deterministic():
    msgs = sim(days=4).generate(ops.FaultSpec(duplicate_frac=0.3))
    r1 = ops.HistoricalReconstructor().reconstruct(msgs, valuation_date=REF, knowledge_date=REF)
    r2 = ops.HistoricalReconstructor().reconstruct(list(reversed(msgs)),
                                                   valuation_date=REF, knowledge_date=REF)
    assert r1.fingerprint == r2.fingerprint


def test_pit_security_filter():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 2)),
            obsmsg("B", "close", 2.0, date(2024, 6, 2))]
    rec = ops.HistoricalReconstructor().reconstruct(
        msgs, valuation_date=REF, knowledge_date=REF, security_ids=["A"])
    assert "A" in rec.snapshot.spots and "B" not in rec.snapshot.spots


def test_pit_arbitration_conflict_dropped():
    a = obsmsg("A", "close", 100.0, date(2024, 6, 2), source="A")
    b = obsmsg("A", "close", 130.0, date(2024, 6, 2), source="B")
    arb = ops.SourceArbiter(ops.ArbitrationConfig(
        ops.ArbitrationPolicy.REJECT_ON_CONFLICT, tolerance_frac=1e-6))
    rec = ops.HistoricalReconstructor(arbiter=arb).reconstruct(
        [a, b], valuation_date=REF, knowledge_date=REF)
    assert "A" not in rec.snapshot.spots


def test_pit_heartbeat_ignored():
    hb = ops.SourceMessage(source="v", payload={}, msg_type=ops.MessageType.HEARTBEAT,
                           observation_date=date(2024, 6, 2))
    good = obsmsg("A", "close", 100.0, date(2024, 6, 2))
    rec = ops.HistoricalReconstructor().reconstruct([hb, good], valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots["A"] == 100.0


# ══════════════════════════════════════════════════════════════════════════════
# 8. Snapshot lifecycle
# ══════════════════════════════════════════════════════════════════════════════

def _rec():
    return ops.HistoricalReconstructor().reconstruct(
        [obsmsg("A", "close", 100.0, date(2024, 6, 2))], valuation_date=REF, knowledge_date=REF)


def test_seal_produces_sealed_state():
    s = ops.seal(_rec())
    assert s.state is ops.SnapshotState.SEALED


def test_seal_verify_true():
    assert ops.seal(_rec()).verify()


def test_seal_pit_status_clean():
    assert ops.seal(_rec()).pit_status == "clean"


def test_seal_carries_source_set():
    assert ops.seal(_rec()).source_set == ("v",)


def test_seal_id_deterministic():
    assert ops.seal(_rec()).snapshot_id == ops.seal(_rec()).snapshot_id


def test_reject_produces_rejected_state():
    r = ops.reject(_rec(), "bad feed")
    assert r.state is ops.SnapshotState.REJECTED and "rejection_reason" in r.quality_summary


def test_seal_verify_fails_on_tamper():
    from dataclasses import replace
    s = ops.seal(_rec())
    tampered = replace(s, snapshot_fingerprint="deadbeef")
    assert not tampered.verify()


def test_seal_n_observations():
    assert ops.seal(_rec()).n_observations == 1


# ══════════════════════════════════════════════════════════════════════════════
# 9. Snapshot store
# ══════════════════════════════════════════════════════════════════════════════

def test_store_put_get():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    sid = store.put(s)
    assert store.get(sid) is s


def test_store_exists_list():
    store = ops.SnapshotStore()
    sid = store.put(ops.seal(_rec()))
    assert store.exists(sid) and store.list_ids() == [sid]


def test_store_metadata():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    store.put(s)
    assert store.metadata(s.snapshot_id)["snapshot_fingerprint"] == s.snapshot_fingerprint


def test_store_by_fingerprint():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    store.put(s)
    assert store.by_fingerprint(s.snapshot_fingerprint) == [s.snapshot_id]


def test_store_by_as_of():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    store.put(s)
    assert store.by_as_of(REF) == [s.snapshot_id]


def test_store_verify():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    store.put(s)
    assert store.verify(s.snapshot_id)


def test_store_missing_get_raises():
    with pytest.raises(KeyError):
        ops.SnapshotStore().get("nope")


def test_store_idempotent_put():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    store.put(s)
    store.put(s)  # same fingerprint → fine
    assert store.list_ids() == [s.snapshot_id]


def test_store_latest():
    store = ops.SnapshotStore()
    s = ops.seal(_rec())
    store.put(s)
    assert store.latest(as_of=REF).snapshot_id == s.snapshot_id


def test_store_directory_persists_envelope(tmp_path):
    d = str(tmp_path / "snaps")
    store = ops.SnapshotStore(directory=d)
    s = ops.seal(_rec())
    store.put(s)
    reloaded = ops.SnapshotStore(directory=d)
    assert reloaded.exists(s.snapshot_id)
    assert reloaded.metadata(s.snapshot_id)["snapshot_fingerprint"] == s.snapshot_fingerprint


def test_store_reload_get_needs_rehydration(tmp_path):
    d = str(tmp_path / "snaps")
    ops.SnapshotStore(directory=d).put(ops.seal(_rec()))
    reloaded = ops.SnapshotStore(directory=d)
    with pytest.raises(ops.SnapshotStoreError):
        reloaded.get(reloaded.list_ids()[0])


# ══════════════════════════════════════════════════════════════════════════════
# 10. Incremental ingestion == full rebuild
# ══════════════════════════════════════════════════════════════════════════════

def test_incremental_equals_full():
    msgs = sim({"A": 1.0, "B": 2.0, "C": 3.0}, days=6).generate(
        ops.FaultSpec(revision_frac=0.3, duplicate_frac=0.2))
    full = ops.MarketDataState()
    full.ingest(msgs)
    inc = ops.MarketDataState()
    for i in range(0, len(msgs), 3):
        inc.ingest(msgs[i:i + 3])
    vd = date(2024, 6, 6)
    assert (full.reconstruct(valuation_date=vd, knowledge_date=vd).snapshot.fingerprint()
            == inc.reconstruct(valuation_date=vd, knowledge_date=vd).snapshot.fingerprint())


def test_incremental_state_fingerprint_order_independent():
    msgs = sim(days=5).generate(ops.FaultSpec(duplicate_frac=0.3))
    a = ops.MarketDataState()
    a.ingest(msgs)
    b = ops.MarketDataState()
    b.ingest(list(reversed(msgs)))
    assert a.fingerprint() == b.fingerprint()


def test_incremental_dedup_counts():
    m = obsmsg("A", "close", 1.0, REF, seq=1)
    st = ops.MarketDataState()
    st.ingest([m])
    rep = st.ingest([m])
    assert rep.duplicates == 1 and rep.added == 0


def test_incremental_late_data_same_final_state():
    early = [obsmsg("A", "close", 1.0, date(2024, 6, 2), ts=datetime(2024, 6, 2, 16), seq=1)]
    late = [obsmsg("A", "bid", 0.9, date(2024, 6, 2), ts=datetime(2024, 6, 4, 16), seq=2)]
    a = ops.MarketDataState()
    a.ingest(early)
    a.ingest(late)
    b = ops.MarketDataState()
    b.ingest(late + early)
    vd = date(2024, 6, 5)
    assert (a.reconstruct(valuation_date=vd, knowledge_date=vd).snapshot.fingerprint()
            == b.reconstruct(valuation_date=vd, knowledge_date=vd).snapshot.fingerprint())


def test_incremental_seal():
    st = ops.MarketDataState()
    st.ingest([obsmsg("A", "close", 1.0, date(2024, 6, 2))])
    s = st.seal(valuation_date=REF, knowledge_date=REF)
    assert s.verify()


def test_incremental_empty_state_reconstructs():
    rec = ops.MarketDataState().reconstruct(valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots == {}


# ══════════════════════════════════════════════════════════════════════════════
# 11. Monitoring (health / coverage / quality)
# ══════════════════════════════════════════════════════════════════════════════

def test_health_connected():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 3))]
    h = ops.HealthMonitor().assess(msgs, as_of=REF)
    assert h["v"].status is ops.FeedStatus.CONNECTED


def test_health_stale():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 5, 1))]
    h = ops.HealthMonitor(stale_after_days=3).assess(msgs, as_of=REF)
    assert h["v"].status is ops.FeedStatus.STALE


def test_health_disconnected_source():
    h = ops.HealthMonitor().assess([], as_of=REF, disconnected_sources=["x"])
    assert h["x"].status is ops.FeedStatus.DISCONNECTED


def test_health_degraded_on_gaps():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 3), seq=1),
            obsmsg("A", "close", 2.0, date(2024, 6, 3), seq=50)]
    ordering = ops.SequenceManager().process(msgs)
    h = ops.HealthMonitor(degraded_error_frac=0.1).assess(msgs, as_of=REF, ordering=ordering)
    assert h["v"].status in (ops.FeedStatus.DEGRADED, ops.FeedStatus.CONNECTED)
    assert h["v"].sequence_gaps >= 1


def test_coverage_all_present():
    msgs = [obsmsg("A", "close", 1.0, REF), obsmsg("B", "close", 2.0, REF)]
    c = ops.coverage(msgs, expected_securities=["A", "B"])
    assert c.complete and c.security_coverage == 1.0


def test_coverage_missing_security():
    msgs = [obsmsg("A", "close", 1.0, REF)]
    c = ops.coverage(msgs, expected_securities=["A", "B"])
    assert c.missing_securities == ("B",) and not c.complete


def test_coverage_missing_fields():
    msgs = [obsmsg("A", "close", 1.0, REF)]
    c = ops.coverage(msgs, expected_securities=["A"], expected_fields=["close", "bid"])
    assert c.missing_fields_by_security == {"A": ("bid",)}


def test_coverage_missing_dates():
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 3))]
    c = ops.coverage(msgs, expected_dates=[date(2024, 6, 3), date(2024, 6, 4)])
    assert c.missing_dates == (date(2024, 6, 4),)


def test_quality_monitor_reject_rate():
    good = obsmsg("A", "close", 100.0, date(2024, 6, 2))
    bad = obsmsg("B", "close", -5.0, date(2024, 6, 2))   # non-positive price → reject
    rep = ops.QualityMonitor().monitor([good, bad], as_of=REF)
    assert rep.rejected >= 1 and rep.reject_rate > 0


def test_quality_monitor_all_clean():
    msgs = [obsmsg("A", "close", 100.0, date(2024, 6, 2))]
    rep = ops.QualityMonitor().monitor(msgs, as_of=REF)
    assert rep.rejected == 0 and rep.accepted == 1


# ══════════════════════════════════════════════════════════════════════════════
# 12. Streaming simulator / fault injection
# ══════════════════════════════════════════════════════════════════════════════

def test_sim_deterministic():
    a = sim(days=4, seed=7).generate(ops.FaultSpec(duplicate_frac=0.5, revision_frac=0.5))
    b = sim(days=4, seed=7).generate(ops.FaultSpec(duplicate_frac=0.5, revision_frac=0.5))
    assert [m.raw_fingerprint() for m in a] == [m.raw_fingerprint() for m in b]


def test_sim_clean_feed_size():
    msgs = sim({"A": 1.0, "B": 2.0}, days=3).generate(ops.FaultSpec())
    assert len(msgs) == 6


def test_sim_duplicates_injected():
    msgs = sim({"A": 1.0}, days=10, seed=1).generate(ops.FaultSpec(duplicate_frac=1.0))
    fps = [m.raw_fingerprint() for m in msgs]
    assert len(fps) != len(set(fps))


def test_sim_drops_reduce_count():
    base = sim({"A": 1.0}, days=10).generate(ops.FaultSpec())
    dropped = sim({"A": 1.0}, days=10, seed=3).generate(ops.FaultSpec(drop_frac=0.5))
    assert len(dropped) < len(base)


def test_sim_reorder_recoverable():
    msgs = sim(days=5, seed=2).generate(ops.FaultSpec(reorder=True))
    ordered = ops.SequenceManager().process(msgs).accepted
    keys = [ops.ordering._order_key(m) for m in ordered]
    assert keys == sorted(keys)


def test_sim_revisions_added():
    msgs = sim({"A": 1.0}, days=10, seed=1).generate(ops.FaultSpec(revision_frac=1.0))
    assert any(m.msg_type is ops.MessageType.REVISION for m in msgs)


def test_sim_malformed_rejected_by_quality():
    msgs = sim({"A": 1.0}, days=10, seed=1).generate(ops.FaultSpec(malformed_frac=1.0))
    rep = ops.QualityMonitor().monitor(msgs, as_of=date(2024, 6, 30))
    # malformed values are non-numeric → normalization drops them (never coerced)
    assert rep.total < len(msgs)


def test_sim_conflicts_create_disagreement():
    msgs = sim({"A": 1.0}, days=5, seed=1).generate(
        ops.FaultSpec(conflict_sources=("B",), conflict_frac=1.0))
    rep = ops.reconcile(msgs)
    assert rep.disagreements


def test_sim_stale_flagged():
    msgs = sim({"A": 1.0}, days=6, seed=1).generate(ops.FaultSpec(stale_frac=1.0))
    rep = ops.SequenceManager(stale_boundary=date(2024, 6, 1)).process(msgs)
    assert rep.event_counts.get("stale", 0) >= 1


def test_sim_fault_free_reconstructs_cleanly():
    msgs = sim({"A": 10.0}, days=4).generate(ops.FaultSpec())
    rec = ops.HistoricalReconstructor().reconstruct(
        msgs, valuation_date=date(2024, 6, 4), knowledge_date=date(2024, 6, 4))
    assert "A" in rec.snapshot.spots


# ══════════════════════════════════════════════════════════════════════════════
# 13. Serialization / integrity
# ══════════════════════════════════════════════════════════════════════════════

def test_message_roundtrip_preserves_fingerprint():
    m = obsmsg("A", "close", 190.0, REF, ts=datetime(2024, 6, 3, 16), seq=3)
    m2 = ops.message_from_dict(ops.message_to_dict(m))
    assert m2.raw_fingerprint() == m.raw_fingerprint()


def test_messages_json_roundtrip():
    msgs = sim(days=3).generate(ops.FaultSpec())
    back = ops.messages_from_json(ops.messages_to_json(msgs))
    assert [m.raw_fingerprint() for m in back] == [m.raw_fingerprint() for m in msgs]


def test_message_corruption_detected():
    m = obsmsg("A", "close", 190.0, REF)
    d = ops.message_to_dict(m)
    d["payload"]["value"] = 999.0            # tamper
    with pytest.raises(ops.DeserializationError):
        ops.message_from_dict(d)


def test_messages_json_sorted_stable():
    msgs = sim(days=3).generate(ops.FaultSpec())
    assert ops.messages_to_json(msgs) == ops.messages_to_json(msgs)


def test_sealed_envelope_json_roundtrip():
    s = ops.seal(_rec())
    env = ops.serialization.sealed_envelope_from_json(ops.sealed_to_json(s))
    assert env["snapshot_id"] == s.snapshot_id


def test_sealed_to_dict_has_fingerprints():
    d = ops.sealed_to_dict(ops.seal(_rec()))
    assert d["snapshot_fingerprint"] and d["reconstruction_fingerprint"]


def test_message_roundtrip_skip_verify():
    m = obsmsg("A", "close", 1.0, REF)
    d = ops.message_to_dict(m)
    d["payload"]["value"] = 2.0
    m2 = ops.message_from_dict(d, verify=False)
    assert float(m2.payload["value"]) == 2.0


# ══════════════════════════════════════════════════════════════════════════════
# 14. M18 valuation integration
# ══════════════════════════════════════════════════════════════════════════════

def test_m18_equity_from_m20_snapshot():
    snap = integ_snapshot()
    r = ValuationEngine().value(ins.equity("AAPL", currency="USD"), snap, ValuationConfiguration())
    assert r.price == 190.0


def test_m18_option_from_m20_snapshot():
    snap = integ_snapshot()
    opt = ins.option("C", underlying="AAPL", strike=200.0, expiry=date(2025, 6, 3),
                     right=ins.OptionRight.CALL, currency="USD")
    r = ValuationEngine().value(opt, snap, ValuationConfiguration())
    assert r.price > 0 and r.greeks.delta > 0


def test_m18_future_from_m20_snapshot():
    snap = integ_snapshot()
    fut = ins.future("F", underlying="AAPL", expiry=date(2024, 12, 3), currency="USD")
    assert ValuationEngine().value(fut, snap, ValuationConfiguration()).price > 190.0


def test_m18_bond_from_m20_snapshot():
    snap = integ_snapshot()
    bond = ins.bond("B", currency="USD", maturity=date(2029, 6, 3), face=100.0, coupon=0.05,
                    frequency=2)
    assert ValuationEngine().value(bond, snap, ValuationConfiguration()).price > 0


def test_m18_portfolio_from_m20_snapshot():
    snap = integ_snapshot()
    eq = ins.equity("AAPL", currency="USD")
    opt = ins.option("C", underlying="AAPL", strike=200.0, expiry=date(2025, 6, 3),
                     right=ins.OptionRight.CALL, currency="USD")
    pv = PortfolioValuationEngine().value([(eq, 100, None), (opt, 10, None)], snap,
                                          ValuationConfiguration())
    assert pv.gross_market_value > 0


def test_m18_valuation_reproducible_from_reconstruction():
    s1, s2 = integ_snapshot(), integ_snapshot()
    eq = ins.equity("AAPL", currency="USD")
    r1 = ValuationEngine().value(eq, s1, ValuationConfiguration())
    r2 = ValuationEngine().value(eq, s2, ValuationConfiguration())
    assert r1.reproducible_key == r2.reproducible_key


# ══════════════════════════════════════════════════════════════════════════════
# 15. M19 reuse integration
# ══════════════════════════════════════════════════════════════════════════════

def test_m19_normalizer_reused_in_reconstruction():
    # percent→rate unit normalization is M19's; reconstruction must inherit it unchanged
    msg = ops.SourceMessage(source="v", payload={"id": "R", "field": "rate", "value": 5.0,
                            "unit": "percent", "observation_date": "2024-06-02"})
    rec = ops.HistoricalReconstructor().reconstruct([msg], valuation_date=REF, knowledge_date=REF)
    obs = [w for w in rec.winners]
    assert obs  # normalized through M19 without M20 re-implementing units


def test_m19_fx_provider_flows_through_engine():
    fx = m16fx.rates.StaticFXRateProvider({"EUR/USD": 1.10})
    eng = ops.MarketDataOperationsEngine(fx_provider=fx)
    eng.ingest([obsmsg("AAPL", "close", 190.0, date(2024, 6, 2))])
    snap = eng.reconstruct_snapshot(valuation_date=REF, knowledge_date=REF).snapshot
    assert snap.fx_rate("EUR", "USD") == 1.10


def test_m19_revision_store_type_reused():
    rec = _rec()
    assert isinstance(rec.revision_store, md.RevisionStore)


def test_m19_quality_engine_composed_by_monitor():
    rep = ops.QualityMonitor().monitor([obsmsg("A", "close", 100.0, date(2024, 6, 2))], as_of=REF)
    assert rep.accepted == 1


# ══════════════════════════════════════════════════════════════════════════════
# 16. Registry / lineage
# ══════════════════════════════════════════════════════════════════════════════

def test_ops_registry_has_ops_components():
    r = ops.default_ops_registry()
    names = {c.name for c in r.all()}
    assert "ops.reconstructor" in names and "ops.replay_engine" in names


def test_ops_registry_includes_m19_components():
    names = {c.name for c in ops.default_ops_registry().all()}
    assert "bootstrap.sequential" in names   # M19 component still present (reused, not replaced)


def test_lineage_captures_fingerprints():
    s = ops.seal(_rec())
    lin = ops.lineage_of(s)
    assert lin.snapshot_fingerprint == s.snapshot_fingerprint and lin.source_set == ("v",)


def test_engine_lineage():
    eng = ops.MarketDataOperationsEngine()
    eng.ingest([obsmsg("A", "close", 1.0, date(2024, 6, 2))])
    s = eng.build_and_seal(valuation_date=REF, knowledge_date=REF)
    assert eng.lineage(s).snapshot_id == s.snapshot_id


# ══════════════════════════════════════════════════════════════════════════════
# 17. Engine façade + determinism
# ══════════════════════════════════════════════════════════════════════════════

def test_engine_ingest_from_adapters():
    eng = ops.MarketDataOperationsEngine()
    eng.add_adapter(ops.LocalSourceAdapter(md.DeterministicMockSource({"A": 100.0})))
    rep = eng.ingest_from_adapters(REF)
    assert rep.added == 1


def test_engine_build_and_seal_stores():
    eng = ops.MarketDataOperationsEngine()
    eng.ingest([obsmsg("A", "close", 1.0, date(2024, 6, 2))])
    s = eng.build_and_seal(valuation_date=REF, knowledge_date=REF)
    assert eng.store.exists(s.snapshot_id)


def test_engine_replay():
    eng = ops.MarketDataOperationsEngine()
    eng.ingest(sim(days=4).generate(ops.FaultSpec()))
    res = eng.replay(ops.ReplayConfig(dates=(date(2024, 6, 3),)), reconstruct=False)
    assert res.total_emitted > 0


def test_engine_health_and_coverage():
    eng = ops.MarketDataOperationsEngine()
    eng.ingest([obsmsg("A", "close", 1.0, date(2024, 6, 3))])
    assert eng.health(as_of=REF)["v"].healthy
    assert eng.coverage(expected_securities=["A"]).complete


def test_engine_state_fingerprint_deterministic():
    e1 = ops.MarketDataOperationsEngine()
    e2 = ops.MarketDataOperationsEngine()
    msgs = sim(days=3).generate(ops.FaultSpec(duplicate_frac=0.4))
    e1.ingest(msgs)
    e2.ingest(list(reversed(msgs)))
    assert e1.state_fingerprint() == e2.state_fingerprint()


# ══════════════════════════════════════════════════════════════════════════════
# 18. Financial / data invariants (consolidated)
# ══════════════════════════════════════════════════════════════════════════════

def test_invariant_duplicates_do_not_change_state():
    msgs = [obsmsg("A", "close", 100.0, date(2024, 6, 2))]
    once = ops.HistoricalReconstructor().reconstruct(msgs, valuation_date=REF, knowledge_date=REF)
    thrice = ops.HistoricalReconstructor().reconstruct(msgs * 3, valuation_date=REF, knowledge_date=REF)
    assert once.snapshot.fingerprint() == thrice.snapshot.fingerprint()


def test_invariant_stale_cannot_become_current():
    stale = obsmsg("A", "close", 50.0, date(2024, 5, 1), ts=datetime(2024, 5, 1, 16))
    fresh = obsmsg("A", "close", 100.0, date(2024, 6, 3), ts=datetime(2024, 6, 3, 16))
    rec = ops.HistoricalReconstructor().reconstruct([stale, fresh], valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots["A"] == 100.0


def test_invariant_identifier_collision_not_merged():
    # two different securities never collapse into one spot
    msgs = [obsmsg("A", "close", 1.0, date(2024, 6, 2)),
            obsmsg("B", "close", 2.0, date(2024, 6, 2))]
    rec = ops.HistoricalReconstructor().reconstruct(msgs, valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots == {"A": 1.0, "B": 2.0}


def test_invariant_provenance_survives_reconstruction():
    rec = _rec()
    assert rec.snapshot.provenance.source == "m19"


def test_invariant_missing_critical_data_fails_closed():
    bad = obsmsg("A", "close", -1.0, date(2024, 6, 2))   # non-positive close
    with pytest.raises(md.SnapshotBuildError):
        ops.HistoricalReconstructor().reconstruct([bad], valuation_date=REF, knowledge_date=REF)


def test_invariant_replay_equals_full_reconstruction_multi_date():
    msgs = sim({"A": 1.0, "B": 2.0}, days=6).generate(ops.FaultSpec(revision_frac=0.3))
    dates = (date(2024, 6, 3), date(2024, 6, 5))
    res = ops.MarketDataReplayEngine(msgs).replay(ops.ReplayConfig(dates=dates))
    for vd in dates:
        direct = ops.HistoricalReconstructor().reconstruct(msgs, valuation_date=vd, knowledge_date=vd)
        assert res.snapshot_on(vd).fingerprint() == direct.snapshot.fingerprint()


def test_invariant_sealed_snapshot_immutable():
    s = ops.seal(_rec())
    with pytest.raises(Exception):
        s.snapshot_id = "x"          # frozen dataclass → cannot mutate


def test_invariant_zero_observations_empty_snapshot():
    rec = ops.HistoricalReconstructor().reconstruct([], valuation_date=REF, knowledge_date=REF)
    assert rec.snapshot.spots == {} and rec.winners == ()


# ══════════════════════════════════════════════════════════════════════════════
# 19. Edge cases / scale
# ══════════════════════════════════════════════════════════════════════════════

def test_edge_single_security_history():
    msgs = [obsmsg("A", "close", 100.0 + i, date(2024, 6, 1) + timedelta(days=i),
                   ts=datetime(2024, 6, 1 + i, 16), seq=i + 1) for i in range(5)]
    rec = ops.HistoricalReconstructor().reconstruct(
        msgs, valuation_date=date(2024, 6, 5), knowledge_date=date(2024, 6, 5))
    assert rec.snapshot.spots["A"] == 104.0     # latest by effective date


def test_edge_large_batch_reconstructs():
    seeds = {f"S{i}": 100.0 + i for i in range(200)}
    msgs = sim(seeds, days=3).generate(ops.FaultSpec())
    rec = ops.HistoricalReconstructor().reconstruct(
        msgs, valuation_date=date(2024, 6, 3), knowledge_date=date(2024, 6, 3))
    assert len(rec.snapshot.spots) == 200


def test_edge_repeated_batch_idempotent():
    msgs = sim(days=3).generate(ops.FaultSpec())
    st = ops.MarketDataState()
    st.ingest(msgs)
    st.ingest(msgs)
    st.ingest(msgs)
    assert len(st.messages) == len(set(m.raw_fingerprint() for m in msgs))


def test_edge_empty_ingest_report():
    rep = ops.MarketDataState().ingest([])
    assert rep.added == 0 and rep.total == 0


def test_edge_all_dropped_still_valid_snapshot():
    msgs = sim({"A": 1.0}, days=20, seed=5).generate(ops.FaultSpec(drop_frac=1.0))
    rec = ops.HistoricalReconstructor().reconstruct(
        msgs, valuation_date=date(2024, 6, 30), knowledge_date=date(2024, 6, 30))
    assert isinstance(rec.snapshot.spots, dict)


def test_edge_reconstruct_far_future_knowledge():
    msgs = [obsmsg("A", "close", 100.0, date(2024, 6, 2), ts=datetime(2024, 6, 2, 16))]
    rec = ops.HistoricalReconstructor().reconstruct(
        msgs, valuation_date=REF, knowledge_date=date(2030, 1, 1))
    assert rec.snapshot.spots["A"] == 100.0
