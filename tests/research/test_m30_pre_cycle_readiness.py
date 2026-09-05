"""M30 — Pre-cycle readiness: dry-runs, data-quality audit, isolation verification.

All tests are deterministic and offline, and none *write* to the real forward
campaign directory. One (T23) reads it read-only to check a real invariant;
every other test uses temporary directories and synthetic / mocked data.

Covers:
  - End-to-end dry-run of ForwardCampaign + AlpacaCycleExecutor (T01–T05)
  - Idempotency: repeat calls produce no duplicates (T06–T08)
  - DataQualityReport checks (T09–T15)
  - Forward campaign isolation from backtest/simulation state (T16–T20)
  - Restart/recovery (T21–T22)
  - No-premature-future-cycle-execution guard (T23) — self-rolling: derives
    "next not-yet-started month" from datetime.now() every run, so it never
    needs a manual date bump the way a hardcoded month eventually would.
  - Strategy fingerprint guard (T24)

DO NOT execute a genuine forward cycle here.
DO NOT write to the real FORWARD_CAMPAIGN_DIR.
DO NOT fabricate forward-campaign evidence.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from mentisrex.research.forward_campaign.alpaca_execution import (
    AlpacaCycleExecutionRecord,
    AlpacaCycleExecutor,
    AlpacaExecutionLedger,
)
from mentisrex.research.forward_campaign.data_quality import (
    DataRisks,
    check_snapshot_quality,
    check_universe_pit_risks,
)
from mentisrex.research.forward_campaign.record import (
    CycleStatus,
    ForwardCycleRecord,
    make_forward_cycle_id,
)

# ── helpers ────────────────────────────────────────────────────────────────────

UNIVERSE = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "JNJ", "V"]

# Deterministic synthetic date — clearly NOT September 2026
DRY_RUN_DATE = date(2026, 7, 1)
DRY_RUN_CYCLE_ID = make_forward_cycle_id("ew-momentum-exp", "1.0.0", DRY_RUN_DATE)


def _fake_cycle_record(
    cycle_id: str = DRY_RUN_CYCLE_ID,
    as_of: date = DRY_RUN_DATE,
    nav: float = 1_000_000.0,
    portfolio_weights: dict | None = None,
    positions: dict | None = None,
    status: str = CycleStatus.SUCCESS,
) -> ForwardCycleRecord:
    rec = ForwardCycleRecord(
        cycle_id=cycle_id,
        strategy_id="ew-momentum-exp",
        strategy_version="1.0.0",
        strategy_fingerprint="b69961b65bab226a500d71f45709945b",
        evaluation_date=date(as_of.year, as_of.month, 1),
        knowledge_as_of=as_of,
        account_id="paper-default",
        campaign_id="DRY_RUN_CAMPAIGN",
        mode="PAPER_FORWARD",
        ending_nav=nav,
        portfolio_weights=portfolio_weights or dict.fromkeys(UNIVERSE, 0.1),
        positions=positions or dict.fromkeys(UNIVERSE, 10.0),
        status=status,
        start_time="2026-07-01T10:00:00",
        end_time="2026-07-01T10:00:01",
    )
    rec.seal(status)
    return rec


def _spot_prices() -> dict[str, float]:
    """Deterministic synthetic spot prices for dry-run tests."""
    return {
        "AAPL": 195.0,
        "MSFT": 410.0,
        "GOOGL": 178.0,
        "AMZN": 195.0,
        "META": 510.0,
        "NVDA": 130.0,
        "TSLA": 250.0,
        "JPM": 210.0,
        "JNJ": 155.0,
        "V": 280.0,
    }


def _fake_broker(equity: float = 1_050_000.0) -> MagicMock:
    """Mocked AlpacaPaperBroker for dry-run: all orders succeed."""
    broker = MagicMock()

    # submit_order returns a mock OrderRecord
    def _submit(symbol, side, quantity, **kw):
        rec = MagicMock()
        rec.alpaca_order_id = f"mock-{symbol}-{side}"
        rec.client_order_id = f"mr-{symbol}-{side}"
        rec.submitted_at = "2026-07-01T10:00:05+00:00"
        rec.status = "accepted"
        return rec

    broker.submit_order.side_effect = _submit

    # get_order_status → immediately filled
    def _status(alpaca_id):
        return {
            "status": "filled",
            "filled_qty": "10",
            "filled_avg_price": "195.0",
            "filled_at": "2026-07-01T10:00:06+00:00",
        }

    broker.get_order_status.side_effect = _status

    # reconcile_positions → PASS
    pos_result = MagicMock()
    pos_result.ok = True
    pos_result.differences = []
    broker.reconcile_positions.return_value = pos_result

    # reconcile_nav → PASS
    nav_result = MagicMock()
    nav_result.ok = True
    nav_result.delta_bps = 2.3
    nav_result.alpaca_equity = equity
    nav_result.internal_nav = 1_000_000.0
    broker.reconcile_nav.return_value = nav_result

    # get_account
    broker.get_account.return_value = {
        "account_id_masked": "MOCK1234...",
        "positions": {},
    }
    return broker


def _fake_snapshot(symbols: list[str] | None = None, missing: list[str] | None = None):
    """Minimal snapshot-like object with .spots dict."""
    syms = symbols or UNIVERSE
    prices = _spot_prices()
    spots: dict = {}
    for s in syms:
        if missing and s in missing:
            continue
        price = prices.get(s, 100.0)
        v = MagicMock()
        v.mid = price
        spots[s] = v
    snap = MagicMock()
    snap.spots = spots
    snap.as_of = DRY_RUN_DATE
    snap.fingerprint.return_value = "dry-run-fingerprint"
    return snap


# ── T01: dry-run AlpacaCycleExecutor completes without error ─────────────────


class TestDryRunExecution(unittest.TestCase):
    def test_executor_completes_with_mock_broker(self):
        """End-to-end dry-run: executor writes sealed record, returns SUCCESS."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            cycle_rec = _fake_cycle_record()
            broker = _fake_broker()
            executor = AlpacaCycleExecutor(data_dir, broker)

            result = executor.execute_cycle(cycle_rec, spot_prices=_spot_prices())

        assert result.status == "SUCCESS"
        assert result.is_sealed
        assert result.cycle_id == DRY_RUN_CYCLE_ID
        assert len(result.orders) > 0
        assert result.reconciliation_status == "PASS"

    def test_executor_writes_json_to_temp_dir(self):
        """Sealed record persists to alpaca_executions/{cycle_id}.json in temp dir."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
            path = data_dir / "alpaca_executions" / f"{DRY_RUN_CYCLE_ID}.json"
            assert path.exists()
            stored = json.loads(path.read_text())
            assert stored["cycle_id"] == DRY_RUN_CYCLE_ID
            assert stored["broker"] == "ALPACA"
            assert stored["environment"] == "PAPER"
            assert stored["live_execution"] == "NO"
            assert stored["real_capital"] == "NO"

    def test_real_campaign_dir_untouched(self):
        """Dry-run uses temp dir; real FORWARD_CAMPAIGN_DIR is never created."""
        real_dir = Path(__file__).resolve().parents[2] / "data" / "forward_campaign"
        before = set(real_dir.glob("**/*")) if real_dir.exists() else set()
        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
        after = set(real_dir.glob("**/*")) if real_dir.exists() else set()
        assert before == after


# ── T06: idempotency — repeat execute_cycle returns same record ───────────────


class TestDryRunIdempotency(unittest.TestCase):
    def test_repeat_execute_returns_existing_no_second_order(self):
        """Second execute_cycle call returns existing sealed record, no orders submitted."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            broker = _fake_broker()
            executor = AlpacaCycleExecutor(data_dir, broker)
            cycle_rec = _fake_cycle_record()

            result1 = executor.execute_cycle(cycle_rec, spot_prices=_spot_prices())
            call_count_after_first = broker.submit_order.call_count

            result2 = executor.execute_cycle(cycle_rec, spot_prices=_spot_prices())

        assert result1.cycle_id == result2.cycle_id
        assert result1.sealed_at == result2.sealed_at
        # No new orders submitted on second call
        assert broker.submit_order.call_count == call_count_after_first

    def test_repeat_execute_does_not_overwrite_json(self):
        """Sealed JSON file is never overwritten by a second execute_cycle."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            cycle_rec = _fake_cycle_record()
            executor.execute_cycle(cycle_rec, spot_prices=_spot_prices())

            path = data_dir / "alpaca_executions" / f"{DRY_RUN_CYCLE_ID}.json"
            mtime1 = path.stat().st_mtime

            executor.execute_cycle(cycle_rec, spot_prices=_spot_prices())
            mtime2 = path.stat().st_mtime

        assert mtime1 == mtime2

    def test_different_cycles_write_separate_files(self):
        """Two different cycle_ids produce separate JSON files."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            d1 = date(2026, 7, 1)
            d2 = date(2026, 6, 1)
            cid1 = make_forward_cycle_id("ew-momentum-exp", "1.0.0", d1)
            cid2 = make_forward_cycle_id("ew-momentum-exp", "1.0.0", d2)
            r1 = _fake_cycle_record(cycle_id=cid1, as_of=d1)
            r2 = _fake_cycle_record(cycle_id=cid2, as_of=d2)

            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            executor.execute_cycle(r1, spot_prices=_spot_prices())
            executor.execute_cycle(r2, spot_prices=_spot_prices())

            files = list((data_dir / "alpaca_executions").glob("*.json"))
        assert len(files) == 2


# ── T09: DataQualityReport ────────────────────────────────────────────────────


class TestDataQualityFullUniverse(unittest.TestCase):
    def test_full_universe_healthy(self):
        snap = _fake_snapshot()
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        assert report.n_expected == 10
        assert report.n_missing == 0
        assert report.n_zero_price == 0
        assert report.coverage_fraction == 1.0
        assert report.coverage_ok
        assert report.sanity_ok
        assert report.is_healthy()

    def test_known_risks_always_present(self):
        snap = _fake_snapshot()
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        for risk in (
            DataRisks.ADJUSTMENT,
            DataRisks.PIT,
            DataRisks.DELISTING,
            DataRisks.REVISION,
            DataRisks.CROSS_PROVIDER,
        ):
            assert risk in report.known_risks


class TestDataQualityMissingSymbols(unittest.TestCase):
    def test_missing_symbol_detected(self):
        snap = _fake_snapshot(missing=["TSLA", "NVDA"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        assert report.n_missing == 2
        assert "TSLA" in report.missing_symbols
        assert "NVDA" in report.missing_symbols

    def test_missing_symbol_reduces_coverage(self):
        snap = _fake_snapshot(missing=["TSLA"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        self.assertAlmostEqual(report.coverage_fraction, 0.9)

    def test_below_threshold_marks_unhealthy(self):
        snap = _fake_snapshot(missing=["TSLA", "NVDA", "META"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE, min_coverage=0.8)
        assert not report.coverage_ok
        assert not report.is_healthy()

    def test_above_threshold_marks_ok(self):
        snap = _fake_snapshot(missing=["TSLA"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE, min_coverage=0.8)
        assert report.coverage_ok


class TestDataQualityZeroPrice(unittest.TestCase):
    def test_zero_price_detected(self):
        snap = _fake_snapshot()
        v = MagicMock()
        v.mid = 0.0
        snap.spots["AAPL"] = v
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        assert report.n_zero_price == 1
        assert "AAPL" in report.zero_price_symbols
        assert not report.sanity_ok
        assert not report.is_healthy()

    def test_negative_price_detected(self):
        snap = _fake_snapshot()
        v = MagicMock()
        v.mid = -5.0
        snap.spots["MSFT"] = v
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        assert "MSFT" in report.zero_price_symbols


class TestDataQualityPitRisks(unittest.TestCase):
    def test_pit_risks_covers_universe(self):
        risks = check_universe_pit_risks(UNIVERSE)
        symbols = [r["symbol"] for r in risks]
        for s in UNIVERSE:
            assert s in symbols

    def test_pit_risks_flags_adjustment_risk(self):
        risks = check_universe_pit_risks(UNIVERSE)
        for r in risks:
            assert r["pit_risk"] == DataRisks.PIT
            assert r["adjustment_risk"] == DataRisks.ADJUSTMENT

    def test_known_split_history_documented(self):
        risks = check_universe_pit_risks(UNIVERSE)
        notes = {r["symbol"]: r["note"] for r in risks}
        # GOOGL, AMZN, TSLA had documented splits
        assert "split" in notes["GOOGL"].lower()
        assert "split" in notes["AMZN"].lower()


# ── T16: isolation — forward campaign doesn't share state with simulation ──────


class TestForwardCampaignIsolation(unittest.TestCase):
    def test_forward_campaign_dir_separate_from_simulation_dir(self):
        """Real campaign dir path must differ from any SIMULATION dir path."""
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        campaign_dir = repo / "data" / "forward_campaign"
        simulation_dir = repo / "data" / "forward_runs"
        assert campaign_dir != simulation_dir

    def test_campaign_checkpoint_path_separate(self):
        """ForwardCampaign._CAMPAIGN_CHECKPOINT is separate from sim checkpoint."""
        from mentisrex.research.forward_campaign.campaign import ForwardCampaign

        assert ForwardCampaign._CAMPAIGN_CHECKPOINT == "campaign_checkpoint.json"
        # The simulation uses "checkpoint.json" (not campaign_checkpoint.json)
        assert ForwardCampaign._CAMPAIGN_CHECKPOINT != "checkpoint.json"

    def test_forward_ledger_reads_from_cycles_subdir(self):
        """ForwardLedger only reads from cycles/ subdir — not from parent dir."""
        from mentisrex.research.forward_campaign.ledger import ForwardLedger

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            # plant a JSON in parent dir — should NOT be picked up
            (data_dir / "stray_cycle.json").write_text('{"cycle_id": "stray"}')
            ledger = ForwardLedger(data_dir)
            cycles = ledger.list_cycles()
        assert cycles == []

    def test_alpaca_execution_ledger_reads_from_exec_subdir(self):
        """AlpacaExecutionLedger only reads from alpaca_executions/ subdir."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            # plant a JSON in parent dir — should NOT be picked up
            (data_dir / "stray_exec.json").write_text('{"cycle_id": "stray"}')
            ledger = AlpacaExecutionLedger(data_dir)
            cycles = ledger.list_cycles()
        assert cycles == []

    def test_forward_cycle_record_mode_is_paper_forward(self):
        """ForwardCycleRecord default mode=PAPER_FORWARD, never SIMULATION."""
        rec = ForwardCycleRecord()
        assert rec.mode == "PAPER_FORWARD"
        assert rec.mode != "SIMULATION"
        assert rec.mode != "BACKTEST"
        assert rec.mode != "REPLAY"


class TestForwardDataIsolation(unittest.TestCase):
    def test_forward_observation_not_written_to_backtest_dir(self):
        """Executing forward cycle in temp dir leaves backtest dirs unchanged."""
        repo = Path(__file__).resolve().parents[2]
        backtest_dirs = list(repo.glob("data/backtests/**/*.json"))
        before_count = len(backtest_dirs)

        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())

        after_count = len(list(repo.glob("data/backtests/**/*.json")))
        assert before_count == after_count

    def test_execution_record_mode_tags(self):
        """All execution records carry ALPACA/PAPER/NO/NO governance tags."""
        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            result = executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())

        assert result.broker == "ALPACA"
        assert result.environment == "PAPER"
        assert result.live_execution == "NO"
        assert result.real_capital == "NO"


# ── T21: restart/recovery ─────────────────────────────────────────────────────


class TestRestartRecovery(unittest.TestCase):
    def test_stale_tmp_file_does_not_block_new_execution(self):
        """A leftover .tmp file from a crashed write does not block the executor."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            exec_dir = data_dir / "alpaca_executions"
            exec_dir.mkdir()
            # Simulate a crash mid-write
            stale_tmp = exec_dir / f"{DRY_RUN_CYCLE_ID}.tmp"
            stale_tmp.write_text('{"cycle_id": "partial"}')

            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            result = executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())

        # Should succeed; the .tmp is not a sealed record
        assert result.status == "SUCCESS"

    def test_ledger_skips_corrupt_json(self):
        """AlpacaExecutionLedger silently skips corrupt JSON files."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            exec_dir = data_dir / "alpaca_executions"
            exec_dir.mkdir()
            # Corrupt file
            (exec_dir / "bad_cycle.json").write_text("not json {{{")
            # Valid file
            rec = AlpacaCycleExecutionRecord(
                cycle_id="good-cycle",
                status="SUCCESS",
                broker="ALPACA",
                environment="PAPER",
            )
            rec.seal("SUCCESS")
            (exec_dir / "good-cycle.json").write_text(
                json.dumps(rec.to_dict(), indent=2, default=str)
            )

            ledger = AlpacaExecutionLedger(data_dir)
            cycles = ledger.list_cycles()

        assert len(cycles) == 1
        assert cycles[0].cycle_id == "good-cycle"


# ── T23: September 2026 prerequisites ────────────────────────────────────────


class TestSeptemberPrerequisites(unittest.TestCase):
    def test_september_cycle_id_is_deterministic(self):
        """September cycle_id is deterministic and unique."""
        sep_date = date(2026, 9, 1)
        cid = make_forward_cycle_id("ew-momentum-exp", "1.0.0", sep_date)
        assert cid == "ew-momentum-exp__2026_09"
        # Different from July (dry-run)
        assert cid != DRY_RUN_CYCLE_ID

    def test_september_cycle_not_yet_in_dry_run_dir(self):
        """Dry-run temp dir contains no September cycle record."""
        sep_cid = "ew-momentum-exp__2026_09"
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            # Run July, not September
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
            sep_path = data_dir / "alpaca_executions" / f"{sep_cid}.json"
        assert not sep_path.exists()

    def test_no_premature_future_cycle_execution(self):
        """Real FORWARD_CAMPAIGN_DIR has no execution record for a cycle month
        that has not started yet.

        This replaces two earlier, hardcoded-to-September tests
        (test_today_before_september_2026 / test_campaign_data_dir_not_
        contaminated) that both went stale the moment September 2026 arrived
        — one became a trip-wire needing a monthly manual date bump, the
        other quietly stopped checking anything meaningful once "September"
        was no longer the future. This version derives "next not-yet-started
        month" from datetime.now() on every run and checks the one invariant
        that actually matters — no execution record exists yet for it — so
        it never goes stale and never needs editing again.
        """
        from datetime import datetime

        today = datetime.now().date()
        if today.month == 12:
            next_month = date(today.year + 1, 1, 1)
        else:
            next_month = date(today.year, today.month + 1, 1)
        next_cid = make_forward_cycle_id("ew-momentum-exp", "1.0.0", next_month)

        repo = Path(__file__).resolve().parents[2]
        for p in repo.glob("data/forward_campaign/**/*.json"):
            if next_cid in p.name and "alpaca_executions" in str(p):
                self.fail(
                    f"Execution record found for {next_cid}, a cycle month "
                    f"({next_month.isoformat()}) that has not started yet: {p}"
                )


# ── T24: strategy fingerprint guard ───────────────────────────────────────────


class TestStrategyFingerprintGuard(unittest.TestCase):
    def test_expected_fingerprint(self):
        """Strategy fingerprint remains b69961b65bab226a500d71f45709945b."""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "forward_run"))
        try:
            from spec import SPEC

            assert SPEC.configuration_fingerprint == "b69961b65bab226a500d71f45709945b", (
                "STRATEGY FINGERPRINT CHANGED — strategy has been modified!"
            )
        except ImportError:
            self.skipTest("spec.py not importable from test context")

    def test_execution_record_carries_expected_fingerprint(self):
        """AlpacaCycleExecutionRecord carries the same fingerprint."""
        rec = _fake_cycle_record()
        assert rec.strategy_fingerprint == "b69961b65bab226a500d71f45709945b"

    def test_strategy_not_modified_tag_in_execution(self):
        """Execute cycle: governance fields confirm strategy not modified."""
        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            result = executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
        assert result.strategy_fingerprint == "b69961b65bab226a500d71f45709945b"


if __name__ == "__main__":
    unittest.main()
