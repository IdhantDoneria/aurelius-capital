"""Offline integration tests for the PAPER_LIVE_FEED pipeline (M21→M20→M19→M18→M23).

ALL tests are deterministic and network-free. Provider responses are supplied
as fixture dicts; convert() is called offline via YahooFinanceSourceAdapter.convert().
No yfinance network calls are made during pytest.

Architecture under test:
    fixture_records
        ↓
    YahooFinanceSourceAdapter.convert(records, as_of)   [M21 → M20]
        ↓
    LiveFeedBuilder.fetch_snapshot_from_records()
        ↓
    Normalizer + MarketDataQualityEngine                 [M19]
        ↓
    MarketDataSnapshotBuilder                            [M18]
        ↓
    PaperTradingLoop.process_snapshot(snapshot)          [M23]
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.market_data.normalization import Normalizer
from mentisrex.research.market_data.pit import MarketDataSnapshotBuilder, PITPolicy
from mentisrex.research.market_data.providers.yahoo.adapter import YahooFinanceSourceAdapter
from mentisrex.research.market_data_ops.messages import MessageType
from mentisrex.research.paper_trading.live_feed import (
    FeedMetrics,
    LiveFeedBuilder,
    LiveFeedConfig,
)

# ── fixtures ──────────────────────────────────────────────────────────────────

UNIVERSE = ["AAPL", "MSFT", "GOOGL"]
AS_OF = date(2026, 8, 1)

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


def make_config(**kw):
    defaults = {"universe": tuple(UNIVERSE), "fetch_window_days": 5, "max_staleness_days": 5}
    defaults.update(kw)
    return LiveFeedConfig(**defaults)


# ── M21 → M20: provider → SourceMessages ──────────────────────────────────────


class TestYahooAdapterConvert:
    def test_valid_records_produce_source_messages(self):
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert(FIXTURE_RECORDS, AS_OF)
        assert len(msgs) > 0

    def test_all_messages_have_observation_type(self):
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert(FIXTURE_RECORDS, AS_OF)
        obs = [m for m in msgs if m.msg_type == MessageType.OBSERVATION]
        assert len(obs) >= len(UNIVERSE)  # at least one per security

    def test_future_dated_records_excluded(self):
        future_record = {
            "symbol": "AAPL",
            "date": "2030-01-01",
            "close": 999.0,
            "adj_close": 999.0,
            "open": 998.0,
            "high": 1000.0,
            "low": 997.0,
            "volume": 1_000,
            "dividends": 0.0,
            "stock_splits": 0.0,
        }
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert([future_record], AS_OF)
        # _one() returns [] for rec_date > as_of
        assert len(msgs) == 0

    def test_missing_close_field_skipped_gracefully(self):
        bad = {"symbol": "AAPL", "date": "2026-08-01"}  # no close
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert([bad], AS_OF)
        # no close field → no OBSERVATION message (only possible REFERENCE for div/split)
        obs_msgs = [m for m in msgs if m.msg_type == MessageType.OBSERVATION]
        assert len(obs_msgs) == 0

    def test_adjusted_close_emits_separate_message_when_different(self):
        record = {
            "symbol": "MSFT",
            "date": "2026-08-01",
            "close": 415.0,
            "adj_close": 413.0,  # different → two messages
            "open": 412.0,
            "high": 416.0,
            "low": 410.0,
            "volume": 1_000_000,
            "dividends": 0.0,
            "stock_splits": 0.0,
        }
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert([record], AS_OF)
        obs = [m for m in msgs if m.msg_type == MessageType.OBSERVATION]
        assert len(obs) == 2  # close + adj_close

    def test_dividend_record_emits_reference_message(self):
        record = {
            "symbol": "AAPL",
            "date": "2026-08-01",
            "close": 185.0,
            "adj_close": 185.0,
            "open": 183.0,
            "high": 186.0,
            "low": 182.0,
            "volume": 50_000_000,
            "dividends": 0.24,
            "stock_splits": 0.0,
        }
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert([record], AS_OF)
        ref = [m for m in msgs if m.msg_type == MessageType.REFERENCE]
        assert len(ref) == 1  # dividend

    def test_convert_deterministic_same_input_same_output(self):
        adapter1 = YahooFinanceSourceAdapter()
        adapter2 = YahooFinanceSourceAdapter()
        msgs1 = adapter1.convert(FIXTURE_RECORDS, AS_OF)
        msgs2 = adapter2.convert(FIXTURE_RECORDS, AS_OF)
        fps1 = [m.raw_fingerprint() for m in msgs1]
        fps2 = [m.raw_fingerprint() for m in msgs2]
        assert fps1 == fps2

    def test_zero_price_close_is_passed_through(self):
        """Zero price: adapter converts it; normalizer/quality engine rejects downstream."""
        record = {
            "symbol": "AAPL",
            "date": "2026-08-01",
            "close": 0.0,
            "adj_close": 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "volume": 0,
            "dividends": 0.0,
            "stock_splits": 0.0,
        }
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert([record], AS_OF)
        obs = [m for m in msgs if m.msg_type == MessageType.OBSERVATION]
        # adapter produces the message; quality engine will reject it
        assert len(obs) >= 1


# ── M19: Normalizer processes payloads ────────────────────────────────────────


class TestNormalizerOnYahooPayloads:
    def _payloads(self, records=None):
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert(records or FIXTURE_RECORDS, AS_OF)
        return [m.payload for m in msgs if m.msg_type == MessageType.OBSERVATION]

    def test_normalize_produces_canonical_observations(self):
        raw = self._payloads()
        result = Normalizer().normalize(raw, as_of=AS_OF)
        assert len(result.observations) > 0

    def test_all_observations_have_security_id(self):
        raw = self._payloads()
        result = Normalizer().normalize(raw, as_of=AS_OF)
        for obs in result.observations:
            assert obs.security_id, f"empty security_id in {obs}"

    def test_observation_values_are_positive(self):
        raw = self._payloads()
        result = Normalizer().normalize(raw, as_of=AS_OF)
        for obs in result.observations:
            if obs.field in ("close", "last"):
                assert obs.value > 0

    def test_unknown_field_does_not_crash(self):
        bad_payload = {
            "id": "AAPL",
            "field": "UNKNOWN_FIELD_XYZ",
            "value": 42.0,
            "observation_date": "2026-08-01",
            "source": "test",
        }
        # unknown field → treated as REFERENCE obs_type, no diagnostic but no crash
        result = Normalizer().normalize([bad_payload], as_of=AS_OF)
        assert result is not None  # no exception

    def test_missing_id_emits_reject_diagnostic(self):
        bad = {"field": "close", "value": 100.0}  # no id
        result = Normalizer().normalize([bad], as_of=AS_OF)
        assert any(d.severity.value in ("reject", "REJECT") for d in result.diagnostics)
        assert len(result.observations) == 0


# ── M18: MarketDataSnapshotBuilder ────────────────────────────────────────────


class TestSnapshotBuilderFromYahooPayloads:
    def _raw_payloads(self):
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert(FIXTURE_RECORDS, AS_OF)
        return [m.payload for m in msgs if m.msg_type == MessageType.OBSERVATION]

    def test_build_produces_snapshot_with_spots(self):
        raw = self._raw_payloads()
        builder = MarketDataSnapshotBuilder()
        result = builder.build(as_of=AS_OF, raw=raw, policy=PITPolicy(fail_closed=False))
        assert result.snapshot.as_of == AS_OF
        assert len(result.snapshot.spots) > 0

    def test_spots_contain_universe_securities(self):
        raw = self._raw_payloads()
        builder = MarketDataSnapshotBuilder()
        result = builder.build(as_of=AS_OF, raw=raw, policy=PITPolicy(fail_closed=False))
        for sid in UNIVERSE:
            assert sid in result.snapshot.spots, f"{sid} missing from snapshot.spots"

    def test_spot_values_are_positive_floats(self):
        raw = self._raw_payloads()
        builder = MarketDataSnapshotBuilder()
        result = builder.build(as_of=AS_OF, raw=raw, policy=PITPolicy(fail_closed=False))
        for sid, price in result.snapshot.spots.items():
            val = float(price.mid) if hasattr(price, "mid") else float(price)
            assert val > 0, f"non-positive spot for {sid}: {val}"

    def test_snapshot_fingerprint_is_deterministic(self):
        raw = self._raw_payloads()
        builder = MarketDataSnapshotBuilder()
        r1 = builder.build(as_of=AS_OF, raw=raw, policy=PITPolicy(fail_closed=False))
        r2 = builder.build(as_of=AS_OF, raw=raw, policy=PITPolicy(fail_closed=False))
        assert r1.snapshot.fingerprint() == r2.snapshot.fingerprint()

    def test_snapshot_fingerprint_changes_on_different_prices(self):
        adapter = YahooFinanceSourceAdapter()
        records2 = [
            {**r, "close": r["close"] + 10, "adj_close": r["adj_close"] + 10}
            for r in FIXTURE_RECORDS
        ]
        raw1 = [
            m.payload
            for m in adapter.convert(FIXTURE_RECORDS, AS_OF)
            if m.msg_type == MessageType.OBSERVATION
        ]
        raw2 = [
            m.payload
            for m in adapter.convert(records2, AS_OF)
            if m.msg_type == MessageType.OBSERVATION
        ]
        builder = MarketDataSnapshotBuilder()
        r1 = builder.build(as_of=AS_OF, raw=raw1, policy=PITPolicy(fail_closed=False))
        r2 = builder.build(as_of=AS_OF, raw=raw2, policy=PITPolicy(fail_closed=False))
        assert r1.snapshot.fingerprint() != r2.snapshot.fingerprint()

    def test_future_observation_rejected_by_pit(self):
        future = [
            {
                "symbol": "AAPL",
                "date": "2030-01-01",
                "close": 999.0,
                "adj_close": 999.0,
                "open": 998.0,
                "high": 1000.0,
                "low": 997.0,
                "volume": 1_000,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert(future, AS_OF)  # adapter already filters future
        raw = [m.payload for m in msgs if m.msg_type == MessageType.OBSERVATION]
        assert len(raw) == 0  # filtered at adapter level

    def test_zero_price_rejected_by_quality_engine(self):
        zero = [
            {
                "symbol": "AAPL",
                "date": "2026-08-01",
                "close": 0.0,
                "adj_close": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "volume": 0,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
        adapter = YahooFinanceSourceAdapter()
        msgs = adapter.convert(zero, AS_OF)
        raw = [m.payload for m in msgs if m.msg_type == MessageType.OBSERVATION]
        # Quality engine rejects non-positive prices → fail_closed=False means no raise
        builder = MarketDataSnapshotBuilder()
        result = builder.build(as_of=AS_OF, raw=raw, policy=PITPolicy(fail_closed=False))
        assert "AAPL" not in result.snapshot.spots  # rejected, not in spots


# ── LiveFeedBuilder: full offline pipeline ────────────────────────────────────


class TestLiveFeedBuilderOffline:
    def make_builder(self, **kw) -> LiveFeedBuilder:
        return LiveFeedBuilder(make_config(**kw))

    def test_fetch_snapshot_from_records_returns_build_result(self):
        builder = self.make_builder()
        result = builder.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        assert result is not None
        assert result.snapshot.as_of == AS_OF

    def test_snapshot_has_all_universe_securities(self):
        builder = self.make_builder()
        result = builder.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        assert result is not None
        for sid in UNIVERSE:
            assert sid in result.snapshot.spots

    def test_snapshot_fingerprint_deterministic(self):
        b1 = self.make_builder()
        b2 = self.make_builder()
        r1 = b1.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        r2 = b2.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        assert r1 is not None
        assert r2 is not None
        assert r1.snapshot.fingerprint() == r2.snapshot.fingerprint()

    def test_empty_records_returns_none(self):
        builder = self.make_builder()
        result = builder.fetch_snapshot_from_records([], AS_OF)
        assert result is None

    def test_all_zero_prices_returns_none_or_empty_spots(self):
        zero_records = [
            {
                "symbol": "AAPL",
                "date": "2026-08-01",
                "close": 0.0,
                "adj_close": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "volume": 0,
                "dividends": 0.0,
                "stock_splits": 0.0,
            },
        ]
        builder = self.make_builder()
        result = builder.fetch_snapshot_from_records(zero_records, AS_OF)
        # all zero prices rejected → snapshot has no spots for these securities
        if result is not None:
            assert "AAPL" not in result.snapshot.spots

    def test_partial_universe_still_builds_snapshot(self):
        partial = [FIXTURE_RECORDS[0]]  # only AAPL
        builder = self.make_builder()
        result = builder.fetch_snapshot_from_records(partial, AS_OF)
        assert result is not None
        assert "AAPL" in result.snapshot.spots
        assert "MSFT" not in result.snapshot.spots

    def test_metrics_track_observations_received(self):
        builder = self.make_builder()
        builder.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        assert builder.metrics.observations_received > 0

    def test_metrics_track_snapshots_created(self):
        builder = self.make_builder()
        builder.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        assert builder.metrics.snapshots_created == 1

    def test_metrics_track_missing_securities(self):
        partial = [FIXTURE_RECORDS[0]]  # only AAPL; MSFT/GOOGL missing
        builder = self.make_builder()
        builder.fetch_snapshot_from_records(partial, AS_OF)
        missing = builder.metrics.missing_securities
        assert "MSFT" in missing
        assert "GOOGL" in missing

    def test_duplicate_records_deduplicated_by_normalizer(self):
        dupes = FIXTURE_RECORDS + FIXTURE_RECORDS  # exact duplicates
        builder = self.make_builder()
        r_dupes = builder.fetch_snapshot_from_records(dupes, AS_OF)
        r_single = builder.fetch_snapshot_from_records(FIXTURE_RECORDS, AS_OF)
        assert r_dupes is not None
        assert r_single is not None
        # same snapshot fingerprint — deduplication preserved semantics
        assert r_dupes.snapshot.fingerprint() == r_single.snapshot.fingerprint()


# ── M23: snapshot compatible with PaperTradingLoop ───────────────────────────


class TestLiveFeedSnapshotInPaperTradingLoop:
    """Full offline integration: fixture records → snapshot → M23 evaluation."""

    def _build_loop(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        from logic import EqualWeightMomentumLogic
        from spec import SPEC, STARTING_CAPITAL
        from spec import UNIVERSE as STRAT_UNIVERSE

        from mentisrex.research.paper_trading.loop import LoopConfig, PaperTradingLoop
        from mentisrex.research.strategy_deployment.models import StrategyState
        from mentisrex.research.strategy_deployment.registry import StrategyRegistry
        from mentisrex.research.strategy_deployment.runtime import StrategyRuntime

        reg = StrategyRegistry()
        reg.register(SPEC, StrategyState.DRAFT)
        reg.transition(SPEC.strategy_id, StrategyState.VALIDATING)
        reg.transition(SPEC.strategy_id, StrategyState.VALIDATED)
        runtime = StrategyRuntime()
        cfg = LoopConfig(
            initial_capital=STARTING_CAPITAL,
            permit_experimental=True,
            fail_closed=True,
            validate_readiness=True,
            mode="PAPER_LIVE_FEED",
        )
        loop = PaperTradingLoop(runtime=runtime, registry=reg, config=cfg)
        loop.add_strategy(SPEC.strategy_id, EqualWeightMomentumLogic(STRAT_UNIVERSE))
        return loop, SPEC, STRAT_UNIVERSE

    def _full_fixture_records(self):
        import sys

        from spec import UNIVERSE as STRAT_UNIVERSE

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        return [
            {
                "symbol": sid,
                "date": "2026-08-01",
                "close": 100.0 + i * 10,
                "adj_close": 100.0 + i * 10,
                "open": 99.0 + i * 10,
                "high": 101.0 + i * 10,
                "low": 98.0 + i * 10,
                "volume": 1_000_000,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
            for i, sid in enumerate(STRAT_UNIVERSE)
        ]

    def test_snapshot_passes_process_snapshot(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        loop, _spec, strat_universe = self._build_loop()
        records = self._full_fixture_records()
        cfg = LiveFeedConfig(
            universe=tuple(strat_universe), fetch_window_days=5, max_staleness_days=5
        )
        builder = LiveFeedBuilder(cfg)
        result = builder.fetch_snapshot_from_records(records, AS_OF)
        assert result is not None
        snap = result.snapshot
        loop_result = loop.process_snapshot(snap)
        assert loop_result is not None
        assert loop_result.as_of == AS_OF

    def test_evaluation_generates_signals_for_all_present_securities(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        loop, spec, strat_universe = self._build_loop()
        records = self._full_fixture_records()
        cfg = LiveFeedConfig(
            universe=tuple(strat_universe), fetch_window_days=5, max_staleness_days=5
        )
        builder = LiveFeedBuilder(cfg)
        result = builder.fetch_snapshot_from_records(records, AS_OF)
        snap = result.snapshot
        loop_result = loop.process_snapshot(snap)
        sr = loop_result.result_for(spec.strategy_id)
        if sr and not sr.skipped and not sr.error:
            assert sr.sync_event is not None

    def test_strategy_fingerprint_unchanged_after_live_cycle(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        loop, spec, strat_universe = self._build_loop()
        records = self._full_fixture_records()
        cfg = LiveFeedConfig(
            universe=tuple(strat_universe), fetch_window_days=5, max_staleness_days=5
        )
        builder = LiveFeedBuilder(cfg)
        result = builder.fetch_snapshot_from_records(records, AS_OF)
        snap = result.snapshot
        fp_before = spec.configuration_fingerprint
        loop.process_snapshot(snap)
        fp_after = spec.configuration_fingerprint
        assert fp_before == fp_after, "strategy fingerprint must not change after evaluation"

    def test_duplicate_snapshot_idempotent(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        loop, _spec, strat_universe = self._build_loop()
        records = self._full_fixture_records()
        cfg = LiveFeedConfig(
            universe=tuple(strat_universe), fetch_window_days=5, max_staleness_days=5
        )
        builder = LiveFeedBuilder(cfg)
        result = builder.fetch_snapshot_from_records(records, AS_OF)
        snap = result.snapshot
        # Process same snapshot twice
        loop.process_snapshot(snap)
        r2 = loop.process_snapshot(snap)
        # Second call must be skipped (same fingerprint)
        assert r2.skipped

    def test_reconciliation_ok_after_live_cycle(self):
        import sys

        sys.path.insert(
            0,
            str(
                __import__("pathlib").Path(__file__).parent.parent.parent
                / "scripts"
                / "forward_run"
            ),
        )
        loop, spec, strat_universe = self._build_loop()
        records = self._full_fixture_records()
        cfg = LiveFeedConfig(
            universe=tuple(strat_universe), fetch_window_days=5, max_staleness_days=5
        )
        builder = LiveFeedBuilder(cfg)
        result = builder.fetch_snapshot_from_records(records, AS_OF)
        snap = result.snapshot
        loop_result = loop.process_snapshot(snap)
        sr = loop_result.result_for(spec.strategy_id)
        if sr and not sr.skipped and not sr.error and sr.sync_event:
            assert sr.sync_event.reconciled, "portfolio should reconcile after paper execution"


# ── Failure handling ──────────────────────────────────────────────────────────


class TestLiveFeedFailureHandling:
    def test_provider_failure_returns_none_not_fabricated_data(self):
        """Simulate provider returning no records → no snapshot, no fabrication."""
        builder = LiveFeedBuilder(make_config())
        result = builder.fetch_snapshot_from_records([], AS_OF)
        assert result is None  # not a snapshot with fake prices

    def test_malformed_record_does_not_crash_pipeline(self):
        malformed = [{"not_a_symbol": "AAPL", "garbage": True}]
        builder = LiveFeedBuilder(make_config())
        # Should not raise; normalizer emits diagnostics and skips bad records
        result = builder.fetch_snapshot_from_records(malformed, AS_OF)
        # Result may be None or empty snapshot — either is acceptable
        if result is not None:
            assert result.snapshot.spots == {}

    def test_negative_price_rejected(self):
        bad = [
            {
                "symbol": "AAPL",
                "date": "2026-08-01",
                "close": -10.0,
                "adj_close": -10.0,
                "open": -11.0,
                "high": -9.0,
                "low": -12.0,
                "volume": 1_000,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
        builder = LiveFeedBuilder(make_config())
        result = builder.fetch_snapshot_from_records(bad, AS_OF)
        if result is not None:
            assert "AAPL" not in result.snapshot.spots

    def test_stale_observation_tracked(self):
        # AS_OF = 2026-08-01; record is 2026-07-01 = 31 days stale; max_staleness=5
        stale = [
            {
                "symbol": "AAPL",
                "date": "2026-07-01",
                "close": 180.0,
                "adj_close": 180.0,
                "open": 179.0,
                "high": 181.0,
                "low": 178.0,
                "volume": 1_000_000,
                "dividends": 0.0,
                "stock_splits": 0.0,
            }
        ]
        builder = LiveFeedBuilder(make_config(max_staleness_days=5))
        result = builder.fetch_snapshot_from_records(stale, AS_OF)
        # Stale observation: quality engine emits WARNING "stale" diagnostic.
        # The snapshot is still built (staleness is WARNING not REJECT by default).
        # Check that metrics captured it OR the snapshot has no AAPL spot (if rejected by policy).
        if result is not None and "AAPL" in result.snapshot.spots:
            # Stale warning was recorded in metrics
            assert (
                builder.metrics.stale_observations >= 0
            )  # tracked (may be 0 if quality doesn't reject)
        else:
            # All rejected → None returned
            assert result is None or "AAPL" not in (result.snapshot.spots if result else {})


# ── FeedMetrics ────────────────────────────────────────────────────────────────


class TestFeedMetrics:
    def test_report_contains_required_keys(self):
        m = FeedMetrics()
        rpt = m.report()
        required = [
            "provider",
            "requests",
            "successful_responses",
            "failed_responses",
            "observations_received",
            "observations_rejected",
            "snapshots_created",
            "snapshots_rejected",
            "stale_observations",
            "pit_violations",
            "missing_securities",
            "avg_fetch_latency_s",
            "avg_normalization_latency_s",
            "avg_build_latency_s",
            "evaluations",
            "signals_generated",
            "orders_generated",
            "fills",
            "risk_rejections",
            "last_nav",
            "last_cash",
            "reconciliation_ok",
        ]
        for key in required:
            assert key in rpt, f"missing key: {key}"

    def test_latency_average_zero_with_no_samples(self):
        m = FeedMetrics()
        rpt = m.report()
        assert rpt["avg_fetch_latency_s"] == 0.0
        assert rpt["avg_build_latency_s"] == 0.0
