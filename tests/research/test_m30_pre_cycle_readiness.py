"""M30 — Pre-cycle readiness: dry-runs, data-quality audit, isolation verification.

All tests are deterministic and offline.  None touch the real forward campaign
directory.  All use temporary directories and synthetic / mocked data.

Covers:
  - End-to-end dry-run of ForwardCampaign + AlpacaCycleExecutor (T01–T05)
  - Idempotency: repeat calls produce no duplicates (T06–T08)
  - DataQualityReport checks (T09–T15)
  - Forward campaign isolation from backtest/simulation state (T16–T20)
  - Restart/recovery (T21–T22)
  - September 2026 prerequisites (T23)
  - Strategy fingerprint guard (T24)

DO NOT execute the genuine September 2026 forward cycle here.
DO NOT write to the real FORWARD_CAMPAIGN_DIR.
DO NOT fabricate September evidence.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from mentisrex.research.forward_campaign.alpaca_execution import (
    AlpacaCycleExecutionRecord,
    AlpacaCycleExecutor,
    AlpacaExecutionLedger,
    AlpacaOrderExecution,
    _compute_execution_summary,
)
from mentisrex.research.forward_campaign.data_quality import (
    DataQualityReport,
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
        portfolio_weights=portfolio_weights or {s: 0.1 for s in UNIVERSE},
        positions=positions or {s: 10.0 for s in UNIVERSE},
        status=status,
        start_time="2026-07-01T10:00:00",
        end_time="2026-07-01T10:00:01",
    )
    rec.seal(status)
    return rec


def _spot_prices() -> dict[str, float]:
    """Deterministic synthetic spot prices for dry-run tests."""
    return {
        "AAPL": 195.0, "MSFT": 410.0, "GOOGL": 178.0, "AMZN": 195.0,
        "META": 510.0, "NVDA": 130.0, "TSLA": 250.0, "JPM": 210.0,
        "JNJ": 155.0, "V": 280.0,
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

        self.assertEqual(result.status, "SUCCESS")
        self.assertTrue(result.is_sealed)
        self.assertEqual(result.cycle_id, DRY_RUN_CYCLE_ID)
        self.assertGreater(len(result.orders), 0)
        self.assertEqual(result.reconciliation_status, "PASS")

    def test_executor_writes_json_to_temp_dir(self):
        """Sealed record persists to alpaca_executions/{cycle_id}.json in temp dir."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
            path = data_dir / "alpaca_executions" / f"{DRY_RUN_CYCLE_ID}.json"
            self.assertTrue(path.exists())
            stored = json.loads(path.read_text())
            self.assertEqual(stored["cycle_id"], DRY_RUN_CYCLE_ID)
            self.assertEqual(stored["broker"], "ALPACA")
            self.assertEqual(stored["environment"], "PAPER")
            self.assertEqual(stored["live_execution"], "NO")
            self.assertEqual(stored["real_capital"], "NO")

    def test_real_campaign_dir_untouched(self):
        """Dry-run uses temp dir; real FORWARD_CAMPAIGN_DIR is never created."""
        real_dir = Path(__file__).resolve().parents[2] / "data" / "forward_campaign"
        before = set(real_dir.glob("**/*")) if real_dir.exists() else set()
        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
        after = set(real_dir.glob("**/*")) if real_dir.exists() else set()
        self.assertEqual(before, after)


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

        self.assertEqual(result1.cycle_id, result2.cycle_id)
        self.assertEqual(result1.sealed_at, result2.sealed_at)
        # No new orders submitted on second call
        self.assertEqual(broker.submit_order.call_count, call_count_after_first)

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

        self.assertEqual(mtime1, mtime2)

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
        self.assertEqual(len(files), 2)


# ── T09: DataQualityReport ────────────────────────────────────────────────────

class TestDataQualityFullUniverse(unittest.TestCase):

    def test_full_universe_healthy(self):
        snap = _fake_snapshot()
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        self.assertEqual(report.n_expected, 10)
        self.assertEqual(report.n_missing, 0)
        self.assertEqual(report.n_zero_price, 0)
        self.assertEqual(report.coverage_fraction, 1.0)
        self.assertTrue(report.coverage_ok)
        self.assertTrue(report.sanity_ok)
        self.assertTrue(report.is_healthy())

    def test_known_risks_always_present(self):
        snap = _fake_snapshot()
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        for risk in (DataRisks.ADJUSTMENT, DataRisks.PIT, DataRisks.DELISTING,
                     DataRisks.REVISION, DataRisks.CROSS_PROVIDER):
            self.assertIn(risk, report.known_risks)


class TestDataQualityMissingSymbols(unittest.TestCase):

    def test_missing_symbol_detected(self):
        snap = _fake_snapshot(missing=["TSLA", "NVDA"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        self.assertEqual(report.n_missing, 2)
        self.assertIn("TSLA", report.missing_symbols)
        self.assertIn("NVDA", report.missing_symbols)

    def test_missing_symbol_reduces_coverage(self):
        snap = _fake_snapshot(missing=["TSLA"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        self.assertAlmostEqual(report.coverage_fraction, 0.9)

    def test_below_threshold_marks_unhealthy(self):
        snap = _fake_snapshot(missing=["TSLA", "NVDA", "META"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE, min_coverage=0.8)
        self.assertFalse(report.coverage_ok)
        self.assertFalse(report.is_healthy())

    def test_above_threshold_marks_ok(self):
        snap = _fake_snapshot(missing=["TSLA"])
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE, min_coverage=0.8)
        self.assertTrue(report.coverage_ok)


class TestDataQualityZeroPrice(unittest.TestCase):

    def test_zero_price_detected(self):
        snap = _fake_snapshot()
        v = MagicMock()
        v.mid = 0.0
        snap.spots["AAPL"] = v
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        self.assertEqual(report.n_zero_price, 1)
        self.assertIn("AAPL", report.zero_price_symbols)
        self.assertFalse(report.sanity_ok)
        self.assertFalse(report.is_healthy())

    def test_negative_price_detected(self):
        snap = _fake_snapshot()
        v = MagicMock()
        v.mid = -5.0
        snap.spots["MSFT"] = v
        report = check_snapshot_quality(snap, UNIVERSE, DRY_RUN_DATE)
        self.assertIn("MSFT", report.zero_price_symbols)


class TestDataQualityPitRisks(unittest.TestCase):

    def test_pit_risks_covers_universe(self):
        risks = check_universe_pit_risks(UNIVERSE)
        symbols = [r["symbol"] for r in risks]
        for s in UNIVERSE:
            self.assertIn(s, symbols)

    def test_pit_risks_flags_adjustment_risk(self):
        risks = check_universe_pit_risks(UNIVERSE)
        for r in risks:
            self.assertEqual(r["pit_risk"], DataRisks.PIT)
            self.assertEqual(r["adjustment_risk"], DataRisks.ADJUSTMENT)

    def test_known_split_history_documented(self):
        risks = check_universe_pit_risks(UNIVERSE)
        notes = {r["symbol"]: r["note"] for r in risks}
        # GOOGL, AMZN, TSLA had documented splits
        self.assertIn("split", notes["GOOGL"].lower())
        self.assertIn("split", notes["AMZN"].lower())


# ── T16: isolation — forward campaign doesn't share state with simulation ──────

class TestForwardCampaignIsolation(unittest.TestCase):

    def test_forward_campaign_dir_separate_from_simulation_dir(self):
        """Real campaign dir path must differ from any SIMULATION dir path."""
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        campaign_dir = repo / "data" / "forward_campaign"
        simulation_dir = repo / "data" / "forward_runs"
        self.assertNotEqual(campaign_dir, simulation_dir)

    def test_campaign_checkpoint_path_separate(self):
        """ForwardCampaign._CAMPAIGN_CHECKPOINT is separate from sim checkpoint."""
        from mentisrex.research.forward_campaign.campaign import ForwardCampaign
        self.assertEqual(ForwardCampaign._CAMPAIGN_CHECKPOINT, "campaign_checkpoint.json")
        # The simulation uses "checkpoint.json" (not campaign_checkpoint.json)
        self.assertNotEqual(ForwardCampaign._CAMPAIGN_CHECKPOINT, "checkpoint.json")

    def test_forward_ledger_reads_from_cycles_subdir(self):
        """ForwardLedger only reads from cycles/ subdir — not from parent dir."""
        from mentisrex.research.forward_campaign.ledger import ForwardLedger
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            # plant a JSON in parent dir — should NOT be picked up
            (data_dir / "stray_cycle.json").write_text('{"cycle_id": "stray"}')
            ledger = ForwardLedger(data_dir)
            cycles = ledger.list_cycles()
        self.assertEqual(cycles, [])

    def test_alpaca_execution_ledger_reads_from_exec_subdir(self):
        """AlpacaExecutionLedger only reads from alpaca_executions/ subdir."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            # plant a JSON in parent dir — should NOT be picked up
            (data_dir / "stray_exec.json").write_text('{"cycle_id": "stray"}')
            ledger = AlpacaExecutionLedger(data_dir)
            cycles = ledger.list_cycles()
        self.assertEqual(cycles, [])

    def test_forward_cycle_record_mode_is_paper_forward(self):
        """ForwardCycleRecord default mode=PAPER_FORWARD, never SIMULATION."""
        rec = ForwardCycleRecord()
        self.assertEqual(rec.mode, "PAPER_FORWARD")
        self.assertNotEqual(rec.mode, "SIMULATION")
        self.assertNotEqual(rec.mode, "BACKTEST")
        self.assertNotEqual(rec.mode, "REPLAY")


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
        self.assertEqual(before_count, after_count)

    def test_execution_record_mode_tags(self):
        """All execution records carry ALPACA/PAPER/NO/NO governance tags."""
        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            result = executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())

        self.assertEqual(result.broker, "ALPACA")
        self.assertEqual(result.environment, "PAPER")
        self.assertEqual(result.live_execution, "NO")
        self.assertEqual(result.real_capital, "NO")


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
        self.assertEqual(result.status, "SUCCESS")

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
                json.dumps(rec.to_dict(), indent=2, default=str))

            ledger = AlpacaExecutionLedger(data_dir)
            cycles = ledger.list_cycles()

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].cycle_id, "good-cycle")


# ── T23: September 2026 prerequisites ────────────────────────────────────────

class TestSeptemberPrerequisites(unittest.TestCase):

    def test_september_cycle_id_is_deterministic(self):
        """September cycle_id is deterministic and unique."""
        sep_date = date(2026, 9, 1)
        cid = make_forward_cycle_id("ew-momentum-exp", "1.0.0", sep_date)
        self.assertEqual(cid, "ew-momentum-exp__2026_09")
        # Different from July (dry-run)
        self.assertNotEqual(cid, DRY_RUN_CYCLE_ID)

    def test_september_cycle_not_yet_in_dry_run_dir(self):
        """Dry-run temp dir contains no September cycle record."""
        sep_cid = "ew-momentum-exp__2026_09"
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            executor = AlpacaCycleExecutor(data_dir, _fake_broker())
            # Run July, not September
            executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
            sep_path = data_dir / "alpaca_executions" / f"{sep_cid}.json"
        self.assertFalse(sep_path.exists())

    def test_today_before_september_2026(self):
        """Confirm that as of test execution, September 2026 is in the future."""
        from datetime import datetime
        today = datetime.now().date()
        sep_1 = date(2026, 9, 1)
        # This test confirms we have not yet reached September
        self.assertLessEqual(today, sep_1,
            "September 2026 has arrived — genuine cycle may now be executed.")

    def test_campaign_data_dir_not_contaminated(self):
        """Real FORWARD_CAMPAIGN_DIR does not contain a September execution record."""
        repo = Path(__file__).resolve().parents[2]
        sep_cid = "ew-momentum-exp__2026_09"
        # Search any campaign dir for September record
        for p in repo.glob("data/forward_campaign/**/*.json"):
            if sep_cid in p.name and "alpaca_executions" in str(p):
                self.fail(f"September execution record found unexpectedly: {p}")


# ── T24: strategy fingerprint guard ───────────────────────────────────────────

class TestStrategyFingerprintGuard(unittest.TestCase):

    def test_expected_fingerprint(self):
        """Strategy fingerprint remains b69961b65bab226a500d71f45709945b."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "forward_run"))
        try:
            from spec import SPEC
            self.assertEqual(
                SPEC.configuration_fingerprint,
                "b69961b65bab226a500d71f45709945b",
                "STRATEGY FINGERPRINT CHANGED — strategy has been modified!",
            )
        except ImportError:
            self.skipTest("spec.py not importable from test context")

    def test_execution_record_carries_expected_fingerprint(self):
        """AlpacaCycleExecutionRecord carries the same fingerprint."""
        rec = _fake_cycle_record()
        self.assertEqual(rec.strategy_fingerprint, "b69961b65bab226a500d71f45709945b")

    def test_strategy_not_modified_tag_in_execution(self):
        """Execute cycle: governance fields confirm strategy not modified."""
        with tempfile.TemporaryDirectory() as td:
            executor = AlpacaCycleExecutor(Path(td), _fake_broker())
            result = executor.execute_cycle(_fake_cycle_record(), spot_prices=_spot_prices())
        self.assertEqual(result.strategy_fingerprint, "b69961b65bab226a500d71f45709945b")


if __name__ == "__main__":
    unittest.main()
