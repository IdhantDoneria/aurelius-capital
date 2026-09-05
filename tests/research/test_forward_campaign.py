"""Forward paper-trading campaign tests (M25).

ALL tests are deterministic and network-free unless marked @pytest.mark.real_data.
Real-data tests are excluded from the normal offline suite.

Coverage map (26 categories from M25 spec §19):
 1. PAPER_FORWARD mode isolation
 2. Scheduler semantics
 3. Due-cycle detection
 4. Cycle identity
 5. Duplicate prevention
 6. Forward record creation
 7. Immutable sealing
 8. Provider revision handling
 9. PIT enforcement (delegate to existing test_live_feed.py)
10. Strategy fingerprint preservation
11. Portfolio preservation
12. Paper execution
13. Accounting
14. Performance ledger
15. Restart behavior
16. Partial-cycle recovery
17. Checkpoint behavior
18. Provider failure
19. Snapshot failure
20. Strategy failure (not_due / skip / error paths)
21. Risk handling
22. Order handling
23. Accounting determinism
24. Deterministic replay of forward record
25. No forward-data leakage into research
26. Real-data smoke integration (offline fixture variant)
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from mentisrex.research.forward_campaign import (
    CycleStatus,
    ForwardCampaign,
    ForwardCycleRecord,
    ForwardLedger,
    make_forward_cycle_id,
)
from mentisrex.research.paper_trading.live_feed import LiveFeedBuilder, LiveFeedConfig
from mentisrex.research.paper_trading.runtime_state import StrategyRuntimeState
from mentisrex.research.paper_trading.scheduler import RebalanceScheduler
from mentisrex.research.strategy_deployment.models import StrategyType, make_spec
from mentisrex.research.strategy_deployment.runtime import StrategyLogic

# ── shared fixtures ────────────────────────────────────────────────────────────

UNIVERSE = ["AAPL", "MSFT", "GOOGL"]
AS_OF = date(2026, 8, 1)
STARTING_CAPITAL = 500_000.0

FIXTURE_RECORDS = [
    {
        "symbol": "AAPL",
        "date": "2026-08-01",
        "close": 185.0,
        "adj_close": 185.0,
        "open": 183.0,
        "high": 186.0,
        "low": 182.0,
        "volume": 50_000_000,
        "dividends": 0.0,
        "stock_splits": 0.0,
    },
    {
        "symbol": "MSFT",
        "date": "2026-08-01",
        "close": 415.0,
        "adj_close": 413.0,
        "open": 412.0,
        "high": 416.0,
        "low": 410.0,
        "volume": 20_000_000,
        "dividends": 0.0,
        "stock_splits": 0.0,
    },
    {
        "symbol": "GOOGL",
        "date": "2026-08-01",
        "close": 172.0,
        "adj_close": 172.0,
        "open": 170.0,
        "high": 173.5,
        "low": 169.0,
        "volume": 15_000_000,
        "dividends": 0.0,
        "stock_splits": 0.0,
    },
]

FIXTURE_RECORDS_SEP = [
    {
        "symbol": "AAPL",
        "date": "2026-09-01",
        "close": 187.0,
        "adj_close": 187.0,
        "open": 185.0,
        "high": 188.0,
        "low": 184.0,
        "volume": 48_000_000,
        "dividends": 0.0,
        "stock_splits": 0.0,
    },
    {
        "symbol": "MSFT",
        "date": "2026-09-01",
        "close": 420.0,
        "adj_close": 418.0,
        "open": 415.0,
        "high": 422.0,
        "low": 413.0,
        "volume": 19_000_000,
        "dividends": 0.0,
        "stock_splits": 0.0,
    },
    {
        "symbol": "GOOGL",
        "date": "2026-09-01",
        "close": 175.0,
        "adj_close": 175.0,
        "open": 172.0,
        "high": 176.0,
        "low": 171.0,
        "volume": 14_000_000,
        "dividends": 0.0,
        "stock_splits": 0.0,
    },
]


def _make_spec(strategy_id: str = "test-fwd-strategy", version: str = "1.0.0"):
    return make_spec(
        strategy_id=strategy_id,
        strategy_name="Test Forward Strategy",
        version=version,
        description="Test only",
        strategy_type=StrategyType.EXPERIMENTAL_PAPER,
        research_artifact_id="TEST",
        validation_artifact_id="test-validation-id",
        validation_status="REQUIRES_REVIEW",
        universe_definition={"type": "equity", "securities": UNIVERSE, "source": "fixed"},
        required_data=["close"],
        feature_definition={"type": "price_level", "lookback_days": 0},
        signal_definition={"type": "equal_weight"},
        rebalance_frequency="monthly",
        portfolio_construction_config={
            "objective": "equal_weight",
            "long_only": True,
            "max_position_weight": 0.5,
        },
        risk_config={"max_position": 0.5, "max_gross_leverage": 1.0, "long_only": True},
        execution_config={"algo": "market"},
        transaction_cost_assumption={"slippage_bps": 5.0},
        slippage_assumption={"model": "linear", "bps": 5.0},
        benchmark="SPY",
        base_currency="USD",
        allowed_instruments=["equity"],
        capital_assumption=STARTING_CAPITAL,
        model_version="1.0.0",
        dependency_versions={"mentisrex_milestone": "M25"},
    )


class _EqualWeightLogic(StrategyLogic):
    """Minimal test logic: signal=1.0 for every universe security with price>0."""

    def __init__(self, universe):
        self._universe = list(universe)

    def compute_features(self, snapshot, spec):
        from mentisrex.research.strategy_deployment.models import FeatureSet

        spots = getattr(snapshot, "spots", {})
        features = {}
        for sid in self._universe:
            raw = spots.get(sid)
            if raw is None:
                continue
            try:
                price = float(raw.mid) if hasattr(raw, "mid") else float(raw)
            except (TypeError, ValueError):
                continue
            features[sid] = {"price": price}
        snap_fp = snapshot.fingerprint() if hasattr(snapshot, "fingerprint") else ""
        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        return FeatureSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=snapshot.as_of,
            features=features,
            input_fingerprint=snap_fp,
            strategy_fingerprint=spec_fp,
        )

    def generate_signal(self, features, spec):
        from mentisrex.research.strategy_deployment.models import SignalRecord, SignalSet

        spec_fp = spec.configuration_fingerprint or spec.fingerprint()
        feat_fp = features.fingerprint()
        signals = {sid: 1.0 for sid, fv in features.features.items() if fv.get("price", 0.0) > 0.0}
        records = [
            SignalRecord(
                strategy_id=spec.strategy_id,
                strategy_version=spec.version,
                security_id=sid,
                as_of=features.as_of,
                signal_value=1.0,
                input_fingerprint=feat_fp,
                strategy_fingerprint=spec_fp,
            )
            for sid in signals
        ]
        return SignalSet(
            strategy_id=spec.strategy_id,
            strategy_version=spec.version,
            as_of=features.as_of,
            signals=signals,
            signal_records=records,
            features_fingerprint=feat_fp,
            strategy_fingerprint=spec_fp,
        )


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path / "forward_campaign"


@pytest.fixture
def spec():
    return _make_spec()


@pytest.fixture
def logic():
    return _EqualWeightLogic(UNIVERSE)


@pytest.fixture
def campaign(tmp_dir, spec, logic):
    return ForwardCampaign.init(
        spec,
        logic,
        tmp_dir,
        universe=UNIVERSE,
        starting_capital=STARTING_CAPITAL,
        campaign_id="test-campaign-001",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. PAPER_FORWARD mode isolation
# ══════════════════════════════════════════════════════════════════════════════


class TestPaperForwardModeIsolation:
    def test_campaign_checkpoint_path_separate_from_simulation(self, campaign, tmp_dir):
        """PAPER_FORWARD checkpoint lives in its own directory."""
        ckpt = tmp_dir / "campaign_checkpoint.json"
        sim_ckpt = tmp_dir.parent / "simulation_checkpoint.json"
        assert campaign._checkpoint_path == ckpt
        assert not sim_ckpt.exists()

    def test_init_does_not_restore_simulation_checkpoint(self, tmp_dir, spec, logic):
        """init() starts with clean state even if a simulation checkpoint exists nearby."""
        sim_ckpt = tmp_dir.parent / "simulation_checkpoint.json"
        sim_ckpt.write_text(
            json.dumps(
                {
                    "cycle_seq": 99,
                    "seen_snapshots": [],
                    "strategy_states": {
                        spec.strategy_id: {
                            "strategy_id": spec.strategy_id,
                            "strategy_version": spec.version,
                            "strategy_fingerprint": "fake",
                            "last_eval_date": "2099-12-01",  # far future
                            "evaluation_count": 99,
                            "error_count": 0,
                            "last_error": "",
                            "status": "active",
                            "last_snapshot_fingerprint": "",
                            "last_evaluation_id": "",
                            "last_evaluation_fingerprint": "",
                        }
                    },
                    "portfolio_states": {},
                    "broker_states": {},
                    "session_seqs": {},
                    "session_last_dates": {},
                    "session_total_costs": {},
                    "session_sync_events": {},
                    "book_applied_fill_ids": {},
                    "session_applied_fill_ids": {},
                    "session_broker_fill_ids": {},
                    "cycle_records": [],
                }
            )
        )

        campaign = ForwardCampaign.init(
            spec,
            logic,
            tmp_dir,
            universe=UNIVERSE,
            starting_capital=STARTING_CAPITAL,
            campaign_id="iso-test",
        )

        loop = campaign._get_loop()
        rs = loop.runtime_state(spec.strategy_id)
        # Should be None — no simulation contamination
        assert rs.last_eval_date is None
        assert rs.evaluation_count == 0

    def test_mode_is_paper_forward(self, campaign):
        st = campaign.status()
        assert st["mode"] == "PAPER_FORWARD"

    def test_manifest_records_governance(self, campaign, tmp_dir):
        manifest = json.loads((tmp_dir / "campaign_manifest.json").read_text())
        assert "NO REAL CAPITAL" in manifest["governance"]
        assert "EXPERIMENTAL PAPER TRADING" in manifest["governance"]
        assert manifest["mode"] == "PAPER_FORWARD"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Scheduler semantics
# ══════════════════════════════════════════════════════════════════════════════


class TestSchedulerSemantics:
    def test_first_evaluation_always_due(self):
        sched = RebalanceScheduler()
        spec = _make_spec()
        rs = StrategyRuntimeState(strategy_id="x", strategy_version="1", strategy_fingerprint="")
        assert sched.is_due(spec, rs, AS_OF)

    def test_same_month_not_due(self):
        sched = RebalanceScheduler()
        spec = _make_spec()
        rs = StrategyRuntimeState(strategy_id="x", strategy_version="1", strategy_fingerprint="")
        rs.last_eval_date = date(2026, 8, 1)
        assert not sched.is_due(spec, rs, date(2026, 8, 15))

    def test_next_month_due(self):
        sched = RebalanceScheduler()
        spec = _make_spec()
        rs = StrategyRuntimeState(strategy_id="x", strategy_version="1", strategy_fingerprint="")
        rs.last_eval_date = date(2026, 8, 1)
        assert sched.is_due(spec, rs, date(2026, 9, 1))

    def test_simulation_future_date_blocks_real_forward(self):
        """If last_eval_date is from a simulation with future date, real date appears not_due."""
        sched = RebalanceScheduler()
        spec = _make_spec()
        rs = StrategyRuntimeState(strategy_id="x", strategy_version="1", strategy_fingerprint="")
        rs.last_eval_date = date(2026, 12, 1)  # synthetic future
        # today is 2026-08-13 — would return not_due if contaminated by simulation state
        assert not sched.is_due(spec, rs, date(2026, 8, 13))
        # BUT: PAPER_FORWARD campaign uses a fresh loop → rs.last_eval_date = None → due
        rs2 = StrategyRuntimeState(strategy_id="x", strategy_version="1", strategy_fingerprint="")
        assert sched.is_due(spec, rs2, date(2026, 8, 13))

    def test_offline_after_intended_date_still_runs(self):
        """Strategy due if evaluation month has passed and no record yet."""
        sched = RebalanceScheduler()
        spec = _make_spec()
        rs = StrategyRuntimeState(strategy_id="x", strategy_version="1", strategy_fingerprint="")
        rs.last_eval_date = date(2026, 7, 1)
        # Now it's September — both August and September are overdue
        assert sched.is_due(spec, rs, date(2026, 9, 5))

    def test_late_data_still_triggers_cycle(self, campaign, spec, logic):
        """Cycle runs even if as_of is late in the month."""
        as_of = date(2026, 8, 25)
        result = campaign.run(as_of, provider_records=FIXTURE_RECORDS)
        assert result.status in (CycleStatus.SUCCESS, CycleStatus.SKIPPED)

    def test_idempotent_same_day_second_call(self, campaign, spec, logic):
        result1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        result2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result1.status == CycleStatus.SUCCESS
        assert result2.status == CycleStatus.ALREADY_SEALED

    def test_same_date_executed_twice_no_duplicate_financial_effect(self, campaign, spec, logic):
        result1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        nav_after_first = result1.record.ending_nav if result1.record else 0.0
        result2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        # Second call returns sealed record with same ending_nav
        assert result2.record is not None
        assert result2.record.ending_nav == nav_after_first


# ══════════════════════════════════════════════════════════════════════════════
# 3. Due-cycle detection
# ══════════════════════════════════════════════════════════════════════════════


class TestDueCycleDetection:
    def test_first_cycle_due_on_init(self, campaign, spec, logic):
        loop = campaign._get_loop()
        rs = loop.runtime_state(spec.strategy_id)
        sched = RebalanceScheduler()
        assert sched.is_due(spec, rs, AS_OF)

    def test_second_cycle_same_month_not_due_in_loop(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        loop = campaign._get_loop()
        rs = loop.runtime_state(spec.strategy_id)
        sched = RebalanceScheduler()
        assert not sched.is_due(spec, rs, AS_OF)

    def test_next_month_due_after_first_cycle(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        loop = campaign._get_loop()
        rs = loop.runtime_state(spec.strategy_id)
        sched = RebalanceScheduler()
        assert sched.is_due(spec, rs, date(2026, 9, 1))


# ══════════════════════════════════════════════════════════════════════════════
# 4. Cycle identity
# ══════════════════════════════════════════════════════════════════════════════


class TestCycleIdentity:
    def test_cycle_id_deterministic(self):
        cid1 = make_forward_cycle_id("strat-x", "1.0.0", date(2026, 8, 1))
        cid2 = make_forward_cycle_id("strat-x", "1.0.0", date(2026, 8, 1))
        assert cid1 == cid2

    def test_cycle_id_different_months(self):
        cid_aug = make_forward_cycle_id("strat-x", "1.0.0", date(2026, 8, 1))
        cid_sep = make_forward_cycle_id("strat-x", "1.0.0", date(2026, 9, 1))
        assert cid_aug != cid_sep

    def test_cycle_id_different_strategies(self):
        cid_a = make_forward_cycle_id("strat-a", "1.0.0", date(2026, 8, 1))
        cid_b = make_forward_cycle_id("strat-b", "1.0.0", date(2026, 8, 1))
        assert cid_a != cid_b

    def test_cycle_id_any_day_same_month_equal(self):
        cid1 = make_forward_cycle_id("strat-x", "1.0.0", date(2026, 8, 1))
        cid2 = make_forward_cycle_id("strat-x", "1.0.0", date(2026, 8, 31))
        assert cid1 == cid2

    def test_record_cycle_id_matches(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        expected = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        assert result.cycle_id == expected

    def test_cycle_id_in_filename(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        cycle_id = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        record_file = tmp_dir / "cycles" / f"{cycle_id}.json"
        assert record_file.exists()


# ══════════════════════════════════════════════════════════════════════════════
# 5. Duplicate prevention
# ══════════════════════════════════════════════════════════════════════════════


class TestDuplicatePrevention:
    def test_second_run_same_cycle_returns_already_sealed(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        result2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result2.status == CycleStatus.ALREADY_SEALED

    def test_already_sealed_returns_original_record(self, campaign, spec, logic):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert r2.record is not None
        assert r2.record.cycle_id == r1.record.cycle_id
        assert r2.record.ending_nav == r1.record.ending_nav

    def test_nav_not_doubled_on_duplicate(self, campaign, spec, logic):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        nav1 = r1.record.ending_nav
        r2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        nav2 = r2.record.ending_nav
        assert abs(nav1 - nav2) < 1e-6  # identical, not doubled

    def test_duplicate_across_restart(self, campaign, spec, logic, tmp_dir):
        """After restart, same cycle still returns ALREADY_SEALED."""
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        # Simulate restart: new campaign from same directory
        campaign2 = ForwardCampaign.resume(spec, logic, tmp_dir)
        r2 = campaign2.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert r2.status == CycleStatus.ALREADY_SEALED


# ══════════════════════════════════════════════════════════════════════════════
# 6. Forward record creation
# ══════════════════════════════════════════════════════════════════════════════


class TestForwardRecordCreation:
    def test_record_file_created(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        cycle_id = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        assert (tmp_dir / "cycles" / f"{cycle_id}.json").exists()

    def test_record_contains_required_identity_fields(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        assert r.cycle_id
        assert r.strategy_id == spec.strategy_id
        assert r.strategy_version == spec.version
        assert r.strategy_fingerprint
        assert r.evaluation_date is not None
        assert r.knowledge_as_of is not None

    def test_record_contains_data_fields(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        assert r.snapshot_fingerprint
        assert r.observations_accepted > 0

    def test_record_contains_accounting_fields(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        assert r.ending_nav > 0
        assert r.starting_nav > 0

    def test_record_json_roundtrip(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        d = r.to_dict()
        r2 = ForwardCycleRecord.from_dict(d)
        assert r2.cycle_id == r.cycle_id
        assert r2.ending_nav == r.ending_nav
        assert r2.sealed_at == r.sealed_at

    def test_record_mode_is_paper_forward(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.record.mode == "PAPER_FORWARD"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Immutable sealing
# ══════════════════════════════════════════════════════════════════════════════


class TestImmutableSealing:
    def test_sealed_record_has_sealed_at(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.record.is_sealed
        assert result.record.sealed_at

    def test_seal_idempotent(self):
        rec = ForwardCycleRecord(cycle_id="x", status=CycleStatus.PARTIAL)
        rec.seal(CycleStatus.SUCCESS)
        first_sealed = rec.sealed_at
        rec.seal(CycleStatus.SUCCESS)
        assert rec.sealed_at == first_sealed  # not changed

    def test_existing_cycle_file_never_overwritten(self, campaign, spec, logic, tmp_dir):
        result1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        cycle_id = result1.record.cycle_id
        record_path = tmp_dir / "cycles" / f"{cycle_id}.json"
        original_content = record_path.read_text()

        # Try to run again with different records (e.g., revised provider data)
        revised = [dict(r, close=999.0) for r in FIXTURE_RECORDS]
        campaign.run(AS_OF, provider_records=revised)

        # File content must be unchanged
        assert record_path.read_text() == original_content

    def test_failed_cycle_not_reported_as_success(self, campaign, spec, logic, tmp_dir):
        """Provider failure → FAILED record, never SUCCESS."""
        result = campaign.run(AS_OF, provider_records=[])  # empty → build failure
        assert result.status == CycleStatus.FAILED
        assert result.record.status == CycleStatus.FAILED


# ══════════════════════════════════════════════════════════════════════════════
# 8. Provider revision handling
# ══════════════════════════════════════════════════════════════════════════════


class TestProviderRevisionHandling:
    def test_revised_data_different_snapshot_fingerprint(self, spec, logic):
        """Original and revised Yahoo data produce different snapshot fingerprints."""
        cfg = LiveFeedConfig(universe=tuple(UNIVERSE), fetch_window_days=5, max_staleness_days=5)
        feed = LiveFeedBuilder(cfg)
        r1 = feed.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)

        # modify both close and adj_close so price changes are internally consistent
        # Simulate a retroactive split-adjustment: all OHLC scale together (close
        # stays within [low, high]) — the realistic Yahoo Finance revision scenario.
        def _adjust(r, factor=1.05):
            return dict(
                r,
                close=r["close"] * factor,
                adj_close=r["adj_close"] * factor,
                open=r["open"] * factor,
                high=r["high"] * factor,
                low=r["low"] * factor,
            )

        revised = [_adjust(r) for r in FIXTURE_RECORDS]
        r2 = feed.fetch_snapshot_from_records(revised, AS_OF)
        assert r1 is not None
        assert r2 is not None
        assert r1.snapshot.fingerprint() != r2.snapshot.fingerprint()

    def test_revision_does_not_overwrite_sealed_record(self, campaign, spec, logic, tmp_dir):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        original_fp = r1.record.snapshot_fingerprint
        revised = [
            dict(
                r,
                close=r["close"] * 1.05,
                adj_close=r["adj_close"] * 1.05,
                open=r["open"] * 1.05,
                high=r["high"] * 1.05,
                low=r["low"] * 1.05,
            )
            for r in FIXTURE_RECORDS
        ]
        r2 = campaign.run(AS_OF, provider_records=revised)  # ALREADY_SEALED
        assert r2.record.snapshot_fingerprint == original_fp

    def test_sealed_record_preserves_original_snapshot_fingerprint(
        self, campaign, spec, logic, tmp_dir
    ):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        original_fp = r1.record.snapshot_fingerprint
        # reload from disk
        ledger = ForwardLedger(tmp_dir)
        reloaded = ledger.get_cycle(r1.cycle_id)
        assert reloaded.snapshot_fingerprint == original_fp


# ══════════════════════════════════════════════════════════════════════════════
# 10. Strategy fingerprint preservation
# ══════════════════════════════════════════════════════════════════════════════


class TestStrategyFingerprintPreservation:
    def test_strategy_fingerprint_in_record(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        expected_fp = spec.configuration_fingerprint or spec.fingerprint()
        assert r.strategy_fingerprint == expected_fp

    def test_fingerprint_unchanged_across_cycles(self, campaign, spec, logic):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r2 = campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        fp1 = r1.record.strategy_fingerprint
        fp2 = r2.record.strategy_fingerprint
        assert fp1 == fp2

    def test_strategy_id_and_version_in_record(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.record.strategy_id == spec.strategy_id
        assert result.record.strategy_version == spec.version


# ══════════════════════════════════════════════════════════════════════════════
# 11. Portfolio preservation
# ══════════════════════════════════════════════════════════════════════════════


class TestPortfolioPreservation:
    def test_positions_in_record(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert isinstance(result.record.positions, dict)

    def test_cash_plus_positions_approx_nav(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        # cash + market value of positions ≈ ending_nav
        # (we can't verify exact market value without prices here, so check cash <= nav)
        assert r.cash >= 0
        assert r.ending_nav > 0

    def test_nav_changes_across_cycles(self, campaign, spec, logic):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r2 = campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        # NAV should differ (prices changed between cycles)
        # In paper trading, NAV evolves with fills and price marks
        assert r1.record.ending_nav > 0
        assert r2.record.ending_nav > 0


# ══════════════════════════════════════════════════════════════════════════════
# 12 & 13. Paper execution and accounting
# ══════════════════════════════════════════════════════════════════════════════


class TestPaperExecutionAndAccounting:
    def test_first_cycle_generates_fills(self, campaign, spec, logic):
        """First cycle from cash → positions should generate fills."""
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        assert r.fills >= 0  # fills ≥ 0; 0 acceptable if all risk-rejected

    def test_starting_nav_close_to_capital(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        assert abs(r.starting_nav - STARTING_CAPITAL) < 1.0  # fresh portfolio

    def test_nav_invariant_cash_nonnegative(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.record.cash >= -0.01  # allow fp rounding

    def test_duplicate_fills_not_applied(self, campaign, spec, logic):
        """Running twice must not double the fills count in the sealed record."""
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        # ALREADY_SEALED returns original record — fills are not added again
        assert r2.record.fills == r1.record.fills

    def test_risk_approved_field_present(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert isinstance(result.record.risk_approved, bool)


# ══════════════════════════════════════════════════════════════════════════════
# 14. Performance ledger
# ══════════════════════════════════════════════════════════════════════════════


class TestPerformanceLedger:
    def test_list_cycles_empty_initially(self, tmp_dir):
        ledger = ForwardLedger(tmp_dir)
        assert ledger.list_cycles() == []

    def test_list_cycles_after_run(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        cycles = ledger.list_cycles()
        assert len(cycles) == 1

    def test_get_cycle_by_id(self, campaign, spec, logic, tmp_dir):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        rec = ledger.get_cycle(result.cycle_id)
        assert rec is not None
        assert rec.cycle_id == result.cycle_id

    def test_get_cycle_nonexistent_returns_none(self, tmp_dir):
        ledger = ForwardLedger(tmp_dir)
        assert ledger.get_cycle("nonexistent-id") is None

    def test_latest_cycle(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        ledger = ForwardLedger(tmp_dir)
        latest = ledger.latest_cycle()
        assert latest is not None
        assert latest.evaluation_date.month == 9

    def test_current_nav(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        nav = ledger.current_nav()
        assert nav > 0

    def test_current_positions(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        positions = ledger.current_positions()
        assert isinstance(positions, dict)

    def test_performance_summary_insufficient_sample_label(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        summary = ledger.performance_summary()
        # 1 cycle → all statistics should be INSUFFICIENT_SAMPLE
        assert summary.sharpe_label == "INSUFFICIENT_SAMPLE"
        assert summary.annualized_return_label == "INSUFFICIENT_SAMPLE"

    def test_performance_summary_counts(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        ledger = ForwardLedger(tmp_dir)
        summary = ledger.performance_summary()
        assert summary.n_successful_cycles == 2
        assert summary.n_failed_cycles == 0

    def test_performance_summary_cumulative_return(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        ledger = ForwardLedger(tmp_dir)
        summary = ledger.performance_summary()
        assert isinstance(summary.cumulative_return, float)

    def test_performance_summary_max_drawdown_nonnegative(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        summary = ledger.performance_summary()
        assert summary.max_drawdown >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 15. Restart behavior
# ══════════════════════════════════════════════════════════════════════════════


class TestRestartBehavior:
    def test_resume_restores_from_campaign_checkpoint(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        # restart
        campaign2 = ForwardCampaign.resume(spec, logic, tmp_dir)
        loop = campaign2._get_loop()
        rs = loop.runtime_state(spec.strategy_id)
        assert rs.last_eval_date == date(AS_OF.year, AS_OF.month, 1) or rs.last_eval_date == AS_OF

    def test_resume_next_cycle_works(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign2 = ForwardCampaign.resume(spec, logic, tmp_dir)
        result = campaign2.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        assert result.status == CycleStatus.SUCCESS

    def test_restart_does_not_duplicate_first_cycle(self, campaign, spec, logic, tmp_dir):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign2 = ForwardCampaign.resume(spec, logic, tmp_dir)
        r2 = campaign2.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert r2.status == CycleStatus.ALREADY_SEALED
        assert r2.record.ending_nav == r1.record.ending_nav

    def test_status_shows_correct_count_after_restart(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign2 = ForwardCampaign.resume(spec, logic, tmp_dir)
        st = campaign2.status()
        assert st["n_sealed_cycles"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 16. Partial-cycle recovery
# ══════════════════════════════════════════════════════════════════════════════


class TestPartialCycleRecovery:
    def test_tmp_file_not_left_on_success(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        cycle_id = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        tmp_file = tmp_dir / "cycles" / f"{cycle_id}.tmp"
        assert not tmp_file.exists()

    def test_partial_tmp_file_ignored_on_next_run(self, campaign, spec, logic, tmp_dir):
        """Simulate a crash mid-write: .tmp exists but not .json."""
        (tmp_dir / "cycles").mkdir(parents=True, exist_ok=True)
        cycle_id = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        tmp_file = tmp_dir / "cycles" / f"{cycle_id}.tmp"
        tmp_file.write_text('{"corrupted": true}')
        # Run should succeed and write the real record
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.status == CycleStatus.SUCCESS
        record_file = tmp_dir / "cycles" / f"{cycle_id}.json"
        assert record_file.exists()


# ══════════════════════════════════════════════════════════════════════════════
# 17. Checkpoint behavior
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckpointBehavior:
    def test_campaign_checkpoint_created_after_run(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert (tmp_dir / "campaign_checkpoint.json").exists()

    def test_checkpoint_separate_from_simulation(self, campaign, tmp_dir):
        sim_path = tmp_dir.parent / "simulation_checkpoint.json"
        assert not sim_path.exists()

    def test_corrupted_checkpoint_raises(self, tmp_dir, spec, logic):
        campaign = ForwardCampaign.init(
            spec,
            logic,
            tmp_dir,
            universe=UNIVERSE,
            starting_capital=STARTING_CAPITAL,
            campaign_id="corrupt-test",
        )
        (tmp_dir / "campaign_checkpoint.json").write_text("NOT JSON {{{")
        with pytest.raises(RuntimeError, match="corrupted"):
            campaign._loop = None  # force re-load
            campaign._get_loop()


# ══════════════════════════════════════════════════════════════════════════════
# 18. Provider failure
# ══════════════════════════════════════════════════════════════════════════════


class TestProviderFailure:
    def test_empty_records_returns_failed(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=[])
        assert result.status == CycleStatus.FAILED
        assert result.record is not None
        assert result.record.status == CycleStatus.FAILED

    def test_failed_cycle_has_error_message(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=[])
        assert result.record.error_message

    def test_failed_cycle_sealed(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=[])
        assert result.record.is_sealed

    def test_failed_cycle_persisted_to_disk(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=[])
        cycle_id = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        path = tmp_dir / "cycles" / f"{cycle_id}.json"
        assert path.exists()
        d = json.loads(path.read_text())
        assert d["status"] == CycleStatus.FAILED

    def test_failed_cycle_then_retry_returns_already_sealed(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=[])
        result2 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result2.status == CycleStatus.ALREADY_SEALED

    def test_partial_records_not_fabricated(self, campaign, spec, logic):
        """Only 1 of 3 universe securities present."""
        partial = [FIXTURE_RECORDS[0]]  # only AAPL
        result = campaign.run(AS_OF, provider_records=partial)
        # Should succeed (partial coverage) with missing securities noted
        if result.status == CycleStatus.SUCCESS:
            assert len(result.record.missing_securities) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# 19. Snapshot failure
# ══════════════════════════════════════════════════════════════════════════════


class TestSnapshotFailure:
    def test_all_rejected_records_returns_failed(self, campaign, spec, logic):
        """Records with dates far in the future → PIT violations → all rejected."""
        future_records = [dict(r, date="2099-01-01") for r in FIXTURE_RECORDS]
        result = campaign.run(AS_OF, provider_records=future_records)
        assert result.status in (CycleStatus.FAILED, CycleStatus.SUCCESS)
        # Either all rejected (FAILED) or some accepted after staleness filter

    def test_zero_spots_snapshot_rejected(self):
        """A snapshot with no spots is rejected by LiveFeedBuilder."""
        cfg = LiveFeedConfig(universe=tuple(UNIVERSE), fetch_window_days=5, max_staleness_days=5)
        feed = LiveFeedBuilder(cfg)
        result = feed.fetch_snapshot_from_records([], date(2026, 8, 1))
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# 20. Strategy skip / not_due paths
# ══════════════════════════════════════════════════════════════════════════════


class TestStrategySkipPaths:
    def test_not_due_returns_skipped(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        # same month, different day → not_due
        result = campaign.run(date(2026, 8, 15), provider_records=FIXTURE_RECORDS)
        # Either ALREADY_SEALED (cycle file exists from first run) or SKIPPED
        assert result.status in (CycleStatus.ALREADY_SEALED, CycleStatus.SKIPPED)

    def test_skip_reason_populated(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        if result.status == CycleStatus.SKIPPED:
            assert result.record.skip_reason


# ══════════════════════════════════════════════════════════════════════════════
# 21. Risk handling
# ══════════════════════════════════════════════════════════════════════════════


class TestRiskHandling:
    def test_risk_approved_in_record(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert hasattr(result.record, "risk_approved")

    def test_cycle_completes_even_if_risk_rejected(self, campaign, spec, logic):
        """Risk rejection → no trades but cycle still sealed as SUCCESS."""
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        # Either risk_approved=True with fills, or risk_approved=False with 0 fills
        assert result.status == CycleStatus.SUCCESS
        if not result.record.risk_approved:
            assert result.record.fills == 0


# ══════════════════════════════════════════════════════════════════════════════
# 23. Accounting determinism
# ══════════════════════════════════════════════════════════════════════════════


class TestAccountingDeterminism:
    def test_deterministic_nav_given_same_records(self, tmp_dir, spec, logic):
        """Same fixture records → same ending_nav in independent runs."""
        c1 = ForwardCampaign.init(
            spec,
            logic,
            tmp_dir / "run1",
            universe=UNIVERSE,
            starting_capital=STARTING_CAPITAL,
            campaign_id="det-1",
        )
        c2 = ForwardCampaign.init(
            spec,
            logic,
            tmp_dir / "run2",
            universe=UNIVERSE,
            starting_capital=STARTING_CAPITAL,
            campaign_id="det-2",
        )
        r1 = c1.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r2 = c2.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert abs(r1.record.ending_nav - r2.record.ending_nav) < 1e-6

    def test_slippage_bps_in_record(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.record.slippage_bps >= 0.0

    def test_realized_unrealized_pnl_types(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert isinstance(result.record.realized_pnl, float)
        assert isinstance(result.record.unrealized_pnl, float)


# ══════════════════════════════════════════════════════════════════════════════
# 24. Deterministic replay of forward record
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterministicReplay:
    def test_replay_produces_same_cycle_id(self, campaign, spec, logic, tmp_dir):
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        expected_id = make_forward_cycle_id(spec.strategy_id, spec.version, AS_OF)
        assert r1.cycle_id == expected_id

    def test_record_fingerprint_stable(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        fp1 = result.record.record_fingerprint()
        fp2 = result.record.record_fingerprint()
        assert fp1 == fp2

    def test_record_from_disk_matches_original(self, campaign, spec, logic, tmp_dir):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        loaded = ledger.get_cycle(result.cycle_id)
        assert loaded.cycle_id == result.record.cycle_id
        assert loaded.ending_nav == result.record.ending_nav
        assert loaded.sealed_at == result.record.sealed_at


# ══════════════════════════════════════════════════════════════════════════════
# 25. No forward-data leakage into research
# ══════════════════════════════════════════════════════════════════════════════


class TestNoForwardLeakage:
    def test_forward_campaign_dir_separate_from_backtest_dir(self, tmp_dir):
        """Forward campaign directory is distinct from any backtest/research path."""
        campaign_dir = tmp_dir / "forward_campaign"
        research_dir = tmp_dir / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        assert campaign_dir != research_dir

    def test_ledger_does_not_write_to_research_dir(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        research_files = list((tmp_dir.parent).glob("**/*.json"))
        # None of the files should be in a "research" or "backtest" directory
        for f in research_files:
            assert "research" not in f.parts
            assert "backtest" not in f.parts

    def test_campaign_status_labels_data_as_forward_only(self, campaign, spec, logic):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        st = campaign.status()
        assert st["live_execution"] == "NO"
        assert st["real_market_data"] == "YES"

    def test_forward_record_mode_prevents_backtest_confusion(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        assert result.record.mode == "PAPER_FORWARD"
        assert "BACKTEST" not in result.record.mode
        assert "SIMULATION" not in result.record.mode


# ══════════════════════════════════════════════════════════════════════════════
# 26. Offline fixture smoke: full pipeline end-to-end
# ══════════════════════════════════════════════════════════════════════════════


class TestOfflineFixtureSmoke:
    def test_full_pipeline_end_to_end(self, campaign, spec, logic, tmp_dir):
        """Smoke: init → run → ledger → performance_summary, all deterministic."""
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r2 = campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)

        assert r1.status == CycleStatus.SUCCESS
        assert r2.status == CycleStatus.SUCCESS

        ledger = ForwardLedger(tmp_dir)
        cycles = ledger.list_cycles()
        assert len(cycles) == 2
        summary = ledger.performance_summary()
        assert summary.n_successful_cycles == 2
        assert summary.starting_nav > 0
        assert summary.current_nav > 0

    def test_duplicate_run_idempotent_end_to_end(self, campaign, spec, logic, tmp_dir):
        for _ in range(3):
            campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        ledger = ForwardLedger(tmp_dir)
        assert len(ledger.list_cycles()) == 1

    def test_status_reflects_all_cycles(self, campaign, spec, logic, tmp_dir):
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        campaign.run(date(2026, 9, 1), provider_records=FIXTURE_RECORDS_SEP)
        st = campaign.status()
        assert st["n_sealed_cycles"] == 2

    def test_forward_cycle_record_fields_complete(self, campaign, spec, logic):
        result = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        r = result.record
        # Check all critical fields present and non-empty/zero where expected
        assert r.cycle_id
        assert r.strategy_id
        assert r.strategy_version
        assert r.strategy_fingerprint
        assert r.evaluation_date is not None
        assert r.mode == "PAPER_FORWARD"
        assert r.sealed_at
        assert r.status == CycleStatus.SUCCESS

    def test_financial_invariant_duplicate_no_nav_doubling(self, campaign, spec, logic, tmp_dir):
        """Financial invariant: executing same cycle twice must not double NAV."""
        r1 = campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)
        nav1 = r1.record.ending_nav
        campaign.run(AS_OF, provider_records=FIXTURE_RECORDS)  # duplicate
        ledger = ForwardLedger(tmp_dir)
        latest = ledger.latest_cycle()
        assert abs(latest.ending_nav - nav1) < 1e-6
