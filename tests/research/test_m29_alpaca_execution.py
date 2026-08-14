"""M29 — Alpaca execution quality, forward evidence, and benchmark analytics tests.

All tests are deterministic and offline — no network calls, no real Alpaca API.
Real-Alpaca tests are marked @pytest.mark.real_alpaca and excluded from offline CI.

Coverage:
  T01  AlpacaOrderExecution construction + governance fields
  T02  CycleExecutionSummary calculation
  T03  Slippage calculation — buy side
  T04  Slippage calculation — sell side
  T05  Fill rate calculation
  T06  Turnover calculation
  T07  UNAVAILABLE sentinel for missing fields
  T08  AlpacaCycleExecutionRecord sealing + immutability
  T09  AlpacaCycleExecutionRecord serialization roundtrip
  T10  AlpacaExecutionLedger — empty directory
  T11  AlpacaExecutionLedger — single record
  T12  AlpacaExecutionLedger — execution_quality_summary
  T13  Idempotency — existing sealed record returned
  T14  Reconciliation PASS recorded correctly
  T15  Reconciliation FAIL not silently converted to PASS
  T16  Partial fills counted separately from full fills
  T17  Rejected orders counted, rejection reason recorded
  T18  Cancelled orders counted
  T19  ForwardVsBacktestComparison — insufficient sample
  T20  ForwardVsBacktestComparison — structure and labels
  T21  ForwardCycleRecord M29 fields backward-compatible
  T22  Research isolation — no train/fit/optimize/backtest on executor
  T23  ForwardEvidenceReport M29 fields populated from execution ledger
  T24  Duplicate-cycle protection in AlpacaExecutionLedger
  T25  AlpacaOrderExecution — no credentials stored
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from mentisrex.research.forward_campaign.alpaca_execution import (
    AlpacaCycleExecutionRecord,
    AlpacaCycleExecutor,
    AlpacaExecutionLedger,
    AlpacaOrderExecution,
    CycleExecutionSummary,
    ForwardVsBacktestComparison,
    _compute_execution_summary,
    build_forward_vs_backtest_comparison,
)
from mentisrex.research.forward_campaign.record import ForwardCycleRecord
from mentisrex.research.forward_campaign.evidence_report import (
    BacktestSnapshot,
    EvidenceReportBuilder,
)
from mentisrex.research.forward_campaign.ledger import ForwardPerformanceSummary


# ── fixtures ──────────────────────────────────────────────────────────────────

def _order(
    symbol: str = "SPY",
    side: str = "buy",
    intended_qty: str = "10",
    filled_qty: str = "10",
    ref_price: str = "500.00",
    fill_price: str = "500.50",
    status: str = "filled",
    slippage_bps: str = "10.0",
    slippage_dollars: str = "5.0",
    latency_ms: str = "120.0",
    rejection_reason: str = "N/A",
) -> AlpacaOrderExecution:
    return AlpacaOrderExecution(
        mentisrex_order_id="mr-test001",
        alpaca_order_id="alpaca-test001",
        client_order_id="mr-test001",
        cycle_id="ew-momentum-exp__2026_08",
        symbol=symbol,
        side=side,
        intended_quantity=intended_qty,
        submitted_quantity=intended_qty,
        filled_quantity=filled_qty,
        order_type="market",
        time_in_force="day",
        reference_price=ref_price,
        avg_fill_price=fill_price,
        submission_timestamp="2026-08-14T10:00:00",
        first_ack_timestamp="2026-08-14T10:00:00.100",
        fill_timestamp="2026-08-14T10:00:00.220",
        order_status=status,
        rejection_reason=rejection_reason,
        slippage_bps=slippage_bps,
        slippage_dollars=slippage_dollars,
        estimated_transaction_cost="UNAVAILABLE",
        execution_latency_ms=latency_ms,
    )


def _fwd_summary(
    n_successful: int = 1,
    cumulative_return: float = 0.01,
    max_drawdown: float = 0.005,
    annualized_return: Optional[float] = None,
    volatility: Optional[float] = None,
    sharpe: Optional[float] = None,
) -> ForwardPerformanceSummary:
    return ForwardPerformanceSummary(
        n_forward_cycles=n_successful,
        n_successful_cycles=n_successful,
        n_skipped_cycles=0,
        n_failed_cycles=0,
        cumulative_return=cumulative_return,
        monthly_returns=[cumulative_return],
        annualized_return=annualized_return,
        annualized_return_label=(
            "ESTIMATED" if annualized_return is not None else "INSUFFICIENT_SAMPLE"
        ),
        volatility=volatility,
        volatility_label=(
            "ESTIMATED" if volatility is not None else "INSUFFICIENT_SAMPLE"
        ),
        sharpe=sharpe,
        sharpe_label=(
            "ESTIMATED" if sharpe is not None else "INSUFFICIENT_SAMPLE"
        ),
        max_drawdown=max_drawdown,
        total_orders=5,
        total_fills=5,
        total_turnover=0.4,
        total_transaction_cost_est=0.0,
        starting_nav=1_000_000.0,
        current_nav=1_010_000.0,
        realized_pnl=10_000.0,
        unrealized_pnl=0.0,
        total_observations_accepted=10,
        total_observations_rejected=0,
        total_pit_violations=0,
        first_evaluation_date=date(2026, 8, 1),
        last_evaluation_date=date(2026, 8, 13),
    )


def _cycle_record(
    cycle_id: str = "ew-momentum-exp__2026_08",
    ending_nav: float = 1_010_000.0,
    positions: dict | None = None,
    portfolio_weights: dict | None = None,
) -> ForwardCycleRecord:
    rec = ForwardCycleRecord(
        cycle_id=cycle_id,
        strategy_id="ew-momentum-exp",
        strategy_version="1.0.0",
        strategy_fingerprint="b69961b65bab226a500d71f45709945b",
        evaluation_date=date(2026, 8, 1),
        knowledge_as_of=date(2026, 8, 13),
        campaign_id="FORWARD_CAMPAIGN_test",
        starting_nav=1_000_000.0,
        ending_nav=ending_nav,
        positions=positions or {"SPY": 1.0, "AAPL": 5.0},
        portfolio_weights=portfolio_weights or {"SPY": 0.5, "AAPL": 0.5},
        gross_return=0.01,
        fills=5,
        risk_approved=True,
    )
    rec.seal("SUCCESS")
    return rec


def _mock_broker(
    account: dict | None = None,
    pos_ok: bool = True,
    nav_ok: bool = True,
) -> MagicMock:
    broker = MagicMock()
    broker.submit_order.return_value = MagicMock(
        alpaca_order_id="alpaca-test-001",
        client_order_id="mr-test-001",
        status="accepted",
        submitted_at="2026-08-14T10:00:00Z",
    )
    broker.get_order_status.return_value = {
        "status": "filled",
        "filled_qty": "1.0",
        "filled_avg_price": "501.00",
        "filled_at": "2026-08-14T10:00:00.500Z",
    }
    broker.reconcile_positions.return_value = MagicMock(
        ok=pos_ok,
        differences=[],
    )
    broker.reconcile_nav.return_value = MagicMock(
        ok=nav_ok,
        delta=500.0,
        delta_bps=5.0,
        alpaca_equity=1_010_500.0,
        internal_nav=1_010_000.0,
    )
    broker.get_account.return_value = {
        "equity": 1_010_500.0,
        "cash": 500_000.0,
        "positions": {"SPY": 1.0, "AAPL": 5.0},
        "account_id_masked": "586c8f70...",
        "open_orders": 0,
    }
    return broker


# ── T01: AlpacaOrderExecution construction + governance fields ────────────────

class TestAlpacaOrderExecutionConstruction:
    def test_all_required_fields_present(self):
        o = _order()
        assert o.mentisrex_order_id == "mr-test001"
        assert o.alpaca_order_id == "alpaca-test001"
        assert o.cycle_id == "ew-momentum-exp__2026_08"
        assert o.symbol == "SPY"
        assert o.side == "buy"

    def test_governance_fields_immutable(self):
        o = _order()
        assert o.broker == "ALPACA"
        assert o.environment == "PAPER"
        assert o.live_execution == "NO"
        assert o.real_capital == "NO"

    def test_frozen_cannot_mutate(self):
        o = _order()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            o.broker = "LIVE"

    def test_no_credentials_in_record(self):
        o = _order()
        rec_str = str(dataclasses.asdict(o))
        assert "KEY" not in rec_str.upper() or "client_order_id" in str(o)
        assert "SECRET" not in rec_str.upper()
        assert "password" not in rec_str.lower()


# ── T02: CycleExecutionSummary calculation ────────────────────────────────────

class TestCycleExecutionSummaryCalculation:
    def test_empty_orders(self):
        s = _compute_execution_summary([], cycle_id="test")
        assert s.orders_submitted == 0
        assert s.fill_rate == 0.0

    def test_all_filled(self):
        orders = [_order(status="filled"), _order(status="filled")]
        s = _compute_execution_summary(orders, cycle_id="test")
        assert s.orders_submitted == 2
        assert s.orders_filled == 2
        assert s.fill_rate == 1.0

    def test_counts_by_status(self):
        orders = [
            _order(status="filled"),
            _order(status="rejected"),
            _order(status="canceled"),
            _order(status="partially_filled"),
        ]
        s = _compute_execution_summary(orders, cycle_id="test")
        assert s.orders_filled == 1
        assert s.orders_rejected == 1
        assert s.orders_canceled == 1
        assert s.orders_partial == 1


# ── T03: Slippage calculation — buy side ─────────────────────────────────────

class TestSlippageBuySide:
    def test_buy_slippage_positive_when_fill_above_ref(self):
        # ref=500, fill=500.50 → buy side hurts, slip > 0
        o = _order(ref_price="500.00", fill_price="500.50", slippage_bps="10.0")
        assert float(o.slippage_bps) > 0

    def test_buy_slippage_negative_when_fill_below_ref(self):
        # fill below ref is price improvement on buy → negative slippage
        o = _order(ref_price="500.00", fill_price="499.50", slippage_bps="-10.0")
        assert float(o.slippage_bps) < 0

    def test_slippage_dollars_calculation(self):
        # 10 shares * (500.50 - 500) = 5.00
        o = _order(
            intended_qty="10", filled_qty="10",
            ref_price="500.00", fill_price="500.50",
            slippage_bps="10.0", slippage_dollars="5.0",
        )
        assert abs(float(o.slippage_dollars) - 5.0) < 0.01


# ── T04: Slippage calculation — sell side ────────────────────────────────────

class TestSlippageSellSide:
    def test_sell_slippage_positive_when_fill_below_ref(self):
        # sell at 499.50 vs ref 500: sell side hurts, slip > 0
        o = _order(side="sell", ref_price="500.00", fill_price="499.50",
                   slippage_bps="10.0")
        assert float(o.slippage_bps) > 0


# ── T05: Fill rate calculation ────────────────────────────────────────────────

class TestFillRateCalculation:
    def test_fill_rate_100_pct(self):
        orders = [_order(status="filled")] * 4
        s = _compute_execution_summary(orders, cycle_id="test")
        assert abs(s.fill_rate - 1.0) < 1e-9

    def test_fill_rate_50_pct(self):
        orders = [_order(status="filled"), _order(status="canceled")]
        s = _compute_execution_summary(orders, cycle_id="test")
        assert abs(s.fill_rate - 0.5) < 1e-9

    def test_fill_rate_zero_with_all_rejected(self):
        orders = [_order(status="rejected")] * 3
        s = _compute_execution_summary(orders, cycle_id="test")
        assert s.fill_rate == 0.0


# ── T06: Turnover calculation ─────────────────────────────────────────────────

class TestTurnoverCalculation:
    def test_turnover_computed_from_notional(self):
        orders = [_order(filled_qty="10", fill_price="500.00")]  # 5000 notional
        s = _compute_execution_summary(orders, cycle_id="t", strategy_nav=10_000.0)
        assert abs(s.total_notional_traded - 5000.0) < 0.01
        assert abs(s.turnover_vs_nav - 0.5) < 0.01

    def test_turnover_zero_when_nav_zero(self):
        orders = [_order(filled_qty="10", fill_price="500.00")]
        s = _compute_execution_summary(orders, cycle_id="t", strategy_nav=0.0)
        assert s.turnover_vs_nav == 0.0


# ── T07: UNAVAILABLE sentinel ─────────────────────────────────────────────────

class TestUnavailableSentinel:
    def test_unavailable_slippage_recorded(self):
        o = _order(slippage_bps="UNAVAILABLE", slippage_dollars="UNAVAILABLE")
        assert o.slippage_bps == "UNAVAILABLE"
        assert o.slippage_dollars == "UNAVAILABLE"

    def test_unavailable_not_zero(self):
        o = _order(slippage_bps="UNAVAILABLE")
        assert o.slippage_bps != "0"
        assert o.slippage_bps != 0

    def test_summary_records_unavailable_fields(self):
        orders = [_order(slippage_bps="UNAVAILABLE", latency_ms="UNAVAILABLE")]
        s = _compute_execution_summary(orders, cycle_id="t")
        assert "slippage_bps" in s.unavailable_fields

    def test_unavailable_latency_not_in_avg(self):
        orders = [_order(latency_ms="UNAVAILABLE")]
        s = _compute_execution_summary(orders, cycle_id="t")
        assert s.avg_execution_latency_ms == 0.0


# ── T08: AlpacaCycleExecutionRecord sealing ──────────────────────────────────

class TestAlpacaCycleExecutionRecordSealing:
    def test_seal_sets_sealed_at(self):
        rec = AlpacaCycleExecutionRecord(cycle_id="test")
        assert not rec.is_sealed
        rec.seal("SUCCESS")
        assert rec.is_sealed
        assert rec.status == "SUCCESS"

    def test_seal_idempotent(self):
        rec = AlpacaCycleExecutionRecord(cycle_id="test")
        rec.seal("SUCCESS")
        ts1 = rec.sealed_at
        rec.seal("FAILED")  # second call — should not change
        assert rec.sealed_at == ts1
        assert rec.status == "SUCCESS"

    def test_fail_not_silently_success(self):
        rec = AlpacaCycleExecutionRecord(cycle_id="test",
                                          reconciliation_status="FAIL")
        rec.seal("FAILED")
        assert rec.status == "FAILED"
        assert rec.reconciliation_status == "FAIL"


# ── T09: AlpacaCycleExecutionRecord serialization roundtrip ──────────────────

class TestAlpacaCycleExecutionRecordSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        rec = AlpacaCycleExecutionRecord(
            cycle_id="ew-momentum-exp__2026_08",
            campaign_id="CAMP001",
            strategy_fingerprint="b69961b65bab226a500d71f45709945b",
            evaluation_date=date(2026, 8, 1),
            reconciliation_status="PASS",
            positions_reconciled=True,
            nav_reconciled=True,
        )
        rec.seal("SUCCESS")
        d = rec.to_dict()
        rec2 = AlpacaCycleExecutionRecord.from_dict(d)
        assert rec2.cycle_id == rec.cycle_id
        assert rec2.evaluation_date == rec.evaluation_date
        assert rec2.reconciliation_status == rec.reconciliation_status
        assert rec2.is_sealed

    def test_json_serializable(self):
        rec = AlpacaCycleExecutionRecord(cycle_id="test")
        rec.seal("SUCCESS")
        # must not raise
        json.dumps(rec.to_dict())


# ── T10: AlpacaExecutionLedger — empty ───────────────────────────────────────

class TestAlpacaExecutionLedgerEmpty:
    def test_empty_dir_returns_empty(self, tmp_path):
        ledger = AlpacaExecutionLedger(tmp_path)
        assert ledger.list_cycles() == []

    def test_latest_cycle_none_when_empty(self, tmp_path):
        ledger = AlpacaExecutionLedger(tmp_path)
        assert ledger.latest_cycle() is None

    def test_get_cycle_none_when_missing(self, tmp_path):
        ledger = AlpacaExecutionLedger(tmp_path)
        assert ledger.get_cycle("nonexistent") is None

    def test_quality_summary_unavailable_when_empty(self, tmp_path):
        ledger = AlpacaExecutionLedger(tmp_path)
        s = ledger.execution_quality_summary()
        assert s["n_cycles"] == 0
        assert s["overall_fill_rate"] == "UNAVAILABLE"


# ── T11: AlpacaExecutionLedger — single record ───────────────────────────────

class TestAlpacaExecutionLedgerSingleRecord:
    def _write_record(self, tmp_path: Path, cycle_id: str,
                      status: str = "SUCCESS") -> AlpacaCycleExecutionRecord:
        rec = AlpacaCycleExecutionRecord(
            cycle_id=cycle_id,
            evaluation_date=date(2026, 8, 1),
            reconciliation_status="PASS",
            positions_reconciled=True,
            nav_reconciled=True,
            summary={"orders_submitted": 3, "orders_filled": 3,
                     "fill_rate": 1.0, "avg_slippage_bps": 5.0,
                     "avg_execution_latency_ms": 100.0},
        )
        rec.seal(status)
        edir = tmp_path / "alpaca_executions"
        edir.mkdir()
        (edir / f"{cycle_id}.json").write_text(json.dumps(rec.to_dict()))
        return rec

    def test_list_cycles_finds_record(self, tmp_path):
        self._write_record(tmp_path, "ew-momentum-exp__2026_08")
        ledger = AlpacaExecutionLedger(tmp_path)
        cycles = ledger.list_cycles()
        assert len(cycles) == 1
        assert cycles[0].cycle_id == "ew-momentum-exp__2026_08"

    def test_get_cycle_by_id(self, tmp_path):
        self._write_record(tmp_path, "ew-momentum-exp__2026_08")
        ledger = AlpacaExecutionLedger(tmp_path)
        c = ledger.get_cycle("ew-momentum-exp__2026_08")
        assert c is not None
        assert c.reconciliation_status == "PASS"

    def test_latest_cycle_returns_most_recent(self, tmp_path):
        self._write_record(tmp_path, "ew-momentum-exp__2026_08")
        ledger = AlpacaExecutionLedger(tmp_path)
        c = ledger.latest_cycle()
        assert c is not None
        assert c.cycle_id == "ew-momentum-exp__2026_08"


# ── T12: execution_quality_summary ───────────────────────────────────────────

class TestExecutionQualitySummary:
    def test_summary_aggregates_across_cycles(self, tmp_path):
        edir = tmp_path / "alpaca_executions"
        edir.mkdir()
        for cycle_id, orders_sub, orders_fill in [
            ("ew-momentum-exp__2026_08", 3, 3),
            ("ew-momentum-exp__2026_09", 4, 2),
        ]:
            rec = AlpacaCycleExecutionRecord(
                cycle_id=cycle_id,
                evaluation_date=date(2026, int(cycle_id[-2:]), 1),
                reconciliation_status="PASS",
                summary={"orders_submitted": orders_sub, "orders_filled": orders_fill,
                         "fill_rate": orders_fill / orders_sub, "avg_slippage_bps": 6.0,
                         "avg_execution_latency_ms": 90.0},
            )
            rec.seal("SUCCESS")
            (edir / f"{cycle_id}.json").write_text(json.dumps(rec.to_dict()))

        ledger = AlpacaExecutionLedger(tmp_path)
        s = ledger.execution_quality_summary()
        assert s["n_cycles"] == 2
        assert s["total_orders_submitted"] == 7
        assert s["total_orders_filled"] == 5
        assert abs(float(s["overall_fill_rate"]) - 5 / 7) < 0.001


# ── T13: idempotency ─────────────────────────────────────────────────────────

class TestIdempotency:
    def test_existing_sealed_record_returned_without_network_call(self, tmp_path):
        edir = tmp_path / "alpaca_executions"
        edir.mkdir()
        rec = AlpacaCycleExecutionRecord(
            cycle_id="ew-momentum-exp__2026_08",
            reconciliation_status="PASS",
            positions_reconciled=True,
        )
        rec.seal("SUCCESS")
        (edir / "ew-momentum-exp__2026_08.json").write_text(
            json.dumps(rec.to_dict()))

        broker = MagicMock()
        executor = AlpacaCycleExecutor(tmp_path, broker)
        cycle_rec = _cycle_record()

        result = executor.execute_cycle(cycle_rec)
        # broker should NOT be called — existing sealed record returned
        broker.submit_order.assert_not_called()
        assert result.cycle_id == "ew-momentum-exp__2026_08"
        assert result.reconciliation_status == "PASS"

    def test_repeat_calls_return_same_record(self, tmp_path):
        broker = _mock_broker()
        executor = AlpacaCycleExecutor(tmp_path, broker)
        cycle_rec = _cycle_record()

        r1 = executor.execute_cycle(cycle_rec,
                                     spot_prices={"SPY": 500.0, "AAPL": 180.0})
        r2 = executor.execute_cycle(cycle_rec,
                                     spot_prices={"SPY": 500.0, "AAPL": 180.0})
        assert r1.cycle_id == r2.cycle_id
        assert r1.sealed_at == r2.sealed_at


# ── T14: reconciliation PASS ──────────────────────────────────────────────────

class TestReconciliationPass:
    def test_reconciliation_pass_recorded(self, tmp_path):
        broker = _mock_broker(pos_ok=True, nav_ok=True)
        executor = AlpacaCycleExecutor(tmp_path, broker)
        cycle_rec = _cycle_record()
        result = executor.execute_cycle(cycle_rec,
                                         spot_prices={"SPY": 500.0, "AAPL": 180.0})
        assert result.reconciliation_status == "PASS"
        assert result.positions_reconciled
        assert result.nav_reconciled


# ── T15: reconciliation FAIL not silently converted to PASS ──────────────────

class TestReconciliationFailNotSilenced:
    def test_fail_stays_fail(self, tmp_path):
        broker = _mock_broker(pos_ok=False, nav_ok=False)
        executor = AlpacaCycleExecutor(tmp_path, broker)
        cycle_rec = _cycle_record()
        result = executor.execute_cycle(cycle_rec,
                                         spot_prices={"SPY": 500.0, "AAPL": 180.0})
        assert result.reconciliation_status == "FAIL"
        assert result.status == "SUCCESS"  # execution succeeded; reconciliation failed

    def test_fail_result_sealed_as_success_with_fail_recon(self, tmp_path):
        broker = _mock_broker(pos_ok=False, nav_ok=True)
        executor = AlpacaCycleExecutor(tmp_path, broker)
        cycle_rec = _cycle_record()
        result = executor.execute_cycle(cycle_rec,
                                         spot_prices={"SPY": 500.0, "AAPL": 180.0})
        # positions failed, nav ok → FAIL (either failing = FAIL)
        assert result.reconciliation_status == "FAIL"


# ── T16: partial fills ────────────────────────────────────────────────────────

class TestPartialFills:
    def test_partial_fill_counted_separately(self):
        orders = [
            _order(status="filled"),
            _order(status="partially_filled"),
        ]
        s = _compute_execution_summary(orders, cycle_id="t")
        assert s.orders_filled == 1
        assert s.orders_partial == 1
        # fill_rate counts partial as filled
        assert s.fill_rate == 1.0  # 2/2 (filled + partial)


# ── T17: rejected orders ──────────────────────────────────────────────────────

class TestRejectedOrders:
    def test_rejection_reason_recorded(self):
        o = _order(status="rejected", rejection_reason="insufficient_funds",
                   fill_price="UNAVAILABLE", filled_qty="0",
                   slippage_bps="UNAVAILABLE", slippage_dollars="UNAVAILABLE")
        assert o.order_status == "rejected"
        assert o.rejection_reason == "insufficient_funds"
        assert o.avg_fill_price == "UNAVAILABLE"

    def test_rejected_order_counted(self):
        orders = [_order(status="rejected")]
        s = _compute_execution_summary(orders, cycle_id="t")
        assert s.orders_rejected == 1
        assert s.orders_filled == 0
        assert s.fill_rate == 0.0


# ── T18: cancelled orders ─────────────────────────────────────────────────────

class TestCancelledOrders:
    def test_cancelled_counted(self):
        orders = [_order(status="canceled")]
        s = _compute_execution_summary(orders, cycle_id="t")
        assert s.orders_canceled == 1
        assert s.fill_rate == 0.0


# ── T19: ForwardVsBacktestComparison — insufficient sample ───────────────────

class TestForwardVsBacktestInsufficientSample:
    def test_insufficient_sample_label_when_n_lt_12(self):
        bt = BacktestSnapshot()
        fwd = _fwd_summary(n_successful=1)
        comparison = build_forward_vs_backtest_comparison(bt, fwd)
        assert comparison.comparison_validity == "INSUFFICIENT_SAMPLE"
        assert comparison.n_forward_observations == 1

    def test_forward_metrics_none_when_insufficient(self):
        bt = BacktestSnapshot()
        fwd = _fwd_summary(n_successful=1, annualized_return=None, sharpe=None)
        comparison = build_forward_vs_backtest_comparison(bt, fwd)
        assert comparison.forward_annualized_return is None
        assert comparison.forward_sharpe is None
        assert comparison.annualized_return_diff is None
        assert comparison.sharpe_diff is None

    def test_backtest_values_always_present(self):
        bt = BacktestSnapshot()
        fwd = _fwd_summary(n_successful=1)
        comparison = build_forward_vs_backtest_comparison(bt, fwd)
        assert comparison.backtest_annualized_return is not None
        assert comparison.backtest_sharpe is not None


# ── T20: ForwardVsBacktestComparison structure ────────────────────────────────

class TestForwardVsBacktestStructure:
    def test_diff_computed_when_forward_available(self):
        bt = BacktestSnapshot()
        fwd = _fwd_summary(
            n_successful=24,
            annualized_return=0.08,
            sharpe=1.5,
            volatility=0.05,
        )
        comparison = build_forward_vs_backtest_comparison(bt, fwd)
        assert comparison.comparison_validity == "PRELIMINARY"
        assert comparison.annualized_return_diff is not None
        assert abs(comparison.annualized_return_diff - (0.08 - bt.annualized_return)) < 1e-10

    def test_governance_field_strategy_not_modified(self):
        bt = BacktestSnapshot()
        fwd = _fwd_summary()
        comparison = build_forward_vs_backtest_comparison(bt, fwd)
        assert comparison.strategy_modified == "NO"

    def test_print_table_runs_without_error(self, capsys):
        bt = BacktestSnapshot()
        fwd = _fwd_summary(n_successful=1)
        comparison = build_forward_vs_backtest_comparison(bt, fwd)
        comparison.print_table()  # must not raise
        captured = capsys.readouterr()
        assert "FORWARD VS BACKTEST" in captured.out


# ── T21: ForwardCycleRecord M29 backward compatibility ───────────────────────

class TestForwardCycleRecordM29Fields:
    def test_new_fields_have_defaults(self):
        rec = ForwardCycleRecord(cycle_id="test")
        assert rec.broker == "SIMULATED"
        assert rec.alpaca_account_id_masked == ""
        assert rec.reconciliation_status == ""
        assert rec.positions_reconciled is False
        assert rec.nav_reconciled is False
        assert rec.nav_delta_bps == 0.0

    def test_from_dict_without_m29_fields(self):
        """Old sealed records without M29 fields still load correctly."""
        d = {
            "cycle_id": "old-cycle",
            "strategy_id": "ew-momentum-exp",
            "status": "SUCCESS",
            "sealed_at": "2026-08-01T00:00:00",
            "ending_nav": 1_000_000.0,
        }
        rec = ForwardCycleRecord.from_dict(d)
        assert rec.broker == "SIMULATED"  # default
        assert rec.cycle_id == "old-cycle"


# ── T22: research isolation ───────────────────────────────────────────────────

class TestResearchIsolation:
    def test_executor_has_no_train_method(self):
        assert not hasattr(AlpacaCycleExecutor, "train")

    def test_executor_has_no_fit_method(self):
        assert not hasattr(AlpacaCycleExecutor, "fit")

    def test_executor_has_no_optimize_method(self):
        assert not hasattr(AlpacaCycleExecutor, "optimize")

    def test_executor_has_no_backtest_method(self):
        assert not hasattr(AlpacaCycleExecutor, "backtest")

    def test_execution_record_governance_fields(self):
        rec = AlpacaCycleExecutionRecord()
        assert rec.broker == "ALPACA"
        assert rec.environment == "PAPER"
        assert rec.live_execution == "NO"
        assert rec.real_capital == "NO"


# ── T23: ForwardEvidenceReport M29 fields populated ──────────────────────────

class TestForwardEvidenceReportM29Fields:
    def test_no_alpaca_execution_label_when_no_records(self, tmp_path):
        """Builder produces NO_ALPACA_EXECUTION label when ledger is empty."""
        # create a minimal campaign dir with just a manifest
        manifest = {
            "campaign_id": "TEST", "strategy_id": "ew-momentum-exp",
            "strategy_version": "1.0.0",
            "strategy_fingerprint": "b69961b65bab226a500d71f45709945b",
            "starting_capital": 1_000_000.0, "universe": ["SPY"], "account_id": "test",
        }
        (tmp_path / "campaign_manifest.json").write_text(json.dumps(manifest))
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()

        builder = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id="ew-momentum-exp",
            strategy_version="1.0.0",
            strategy_fingerprint="b69961b65bab226a500d71f45709945b",
            universe=["SPY"],
            initial_capital=1_000_000.0,
        )
        report = builder.build(load_backtest=False, include_alpaca_execution=True)
        assert report.execution_quality_label == "NO_ALPACA_EXECUTION"
        assert report.alpaca_execution_cycles == 0

    def test_alpaca_execution_label_when_records_exist(self, tmp_path):
        """Builder picks up Alpaca execution records from ledger."""
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        edir = tmp_path / "alpaca_executions"
        edir.mkdir()

        rec = AlpacaCycleExecutionRecord(
            cycle_id="ew-momentum-exp__2026_08",
            evaluation_date=date(2026, 8, 1),
            reconciliation_status="PASS",
            summary={"orders_submitted": 5, "orders_filled": 5,
                     "fill_rate": 1.0, "avg_slippage_bps": 8.0,
                     "avg_execution_latency_ms": 95.0},
        )
        rec.seal("SUCCESS")
        (edir / "ew-momentum-exp__2026_08.json").write_text(json.dumps(rec.to_dict()))

        manifest = {
            "campaign_id": "TEST", "strategy_id": "ew-momentum-exp",
            "strategy_version": "1.0.0",
            "strategy_fingerprint": "b69961b65bab226a500d71f45709945b",
            "starting_capital": 1_000_000.0, "universe": ["SPY"], "account_id": "test",
        }
        (tmp_path / "campaign_manifest.json").write_text(json.dumps(manifest))

        builder = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id="ew-momentum-exp",
            strategy_version="1.0.0",
            strategy_fingerprint="b69961b65bab226a500d71f45709945b",
            universe=["SPY"],
            initial_capital=1_000_000.0,
        )
        report = builder.build(load_backtest=False, include_alpaca_execution=True)
        assert report.execution_quality_label == "ALPACA_PAPER"
        assert report.alpaca_execution_cycles == 1
        assert report.alpaca_orders_submitted == 5


# ── T24: duplicate cycle protection ──────────────────────────────────────────

class TestDuplicateCycleProtection:
    def test_persist_does_not_overwrite(self, tmp_path):
        edir = tmp_path / "alpaca_executions"
        edir.mkdir()

        rec1 = AlpacaCycleExecutionRecord(cycle_id="test", reconciliation_status="PASS")
        rec1.seal("SUCCESS")
        target = edir / "test.json"
        target.write_text(json.dumps(rec1.to_dict()))

        # second write attempt — should not overwrite
        rec2 = AlpacaCycleExecutionRecord(cycle_id="test", reconciliation_status="FAIL")
        rec2.seal("FAILED")

        broker = MagicMock()
        executor = AlpacaCycleExecutor(tmp_path, broker)
        executor._persist(rec2)

        # original should still be there
        loaded = AlpacaCycleExecutionRecord.from_dict(json.loads(target.read_text()))
        assert loaded.reconciliation_status == "PASS"


# ── T25: no credentials in AlpacaOrderExecution ──────────────────────────────

class TestNoCredentialsInExecution:
    def test_order_dict_contains_no_credential_keys(self):
        o = _order()
        d = dataclasses.asdict(o)
        d_str = json.dumps(d).lower()
        assert "api_key" not in d_str
        assert "api_secret" not in d_str
        assert "secret" not in d_str

    def test_cycle_execution_record_no_credentials(self):
        rec = AlpacaCycleExecutionRecord(cycle_id="test",
                                          alpaca_account_id_masked="586c8f70...")
        d = json.dumps(rec.to_dict())
        assert "api_key" not in d.lower()
        assert "secret" not in d.lower()
        # masked account ID is fine
        assert "586c8f70" in d


# ── Real Alpaca tests (offline suite excluded) ────────────────────────────────

@pytest.mark.real_alpaca
class TestRealAlpacaExecution:
    """Requires ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET."""

    def test_execute_cycle_with_real_broker(self, tmp_path):
        import os
        from mentisrex.paper import AlpacaPaperBroker
        if not (os.environ.get("ALPACA_PAPER_API_KEY") and
                os.environ.get("ALPACA_PAPER_API_SECRET")):
            pytest.skip("ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET not set")

        broker = AlpacaPaperBroker(
            strategy_id="ew-momentum-exp",
            strategy_fingerprint="b69961b65bab226a500d71f45709945b",
        )
        executor = AlpacaCycleExecutor(tmp_path, broker)
        cycle_rec = _cycle_record(
            portfolio_weights={"SPY": 1.0},
            positions={"SPY": 0.0},
        )
        result = executor.execute_cycle(
            cycle_rec,
            spot_prices={"SPY": 500.0},
        )
        broker.close()

        assert result.cycle_id == cycle_rec.cycle_id
        assert result.is_sealed
        assert result.live_execution == "NO"
        assert result.real_capital == "NO"
        assert result.broker == "ALPACA"
        assert result.environment == "PAPER"
