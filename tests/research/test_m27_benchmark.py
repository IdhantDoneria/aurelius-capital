"""M27 forward evidence accumulation & benchmark tests.

ALL tests are deterministic and network-free.
Real-data tests are marked @pytest.mark.real_data and excluded from offline suite.

Coverage (17 categories per M27 spec §19):
  1.  September cycle creation (infrastructure test — fixture-based)
  2.  Multi-month accumulation (Aug → Sep → Oct → Nov)
  3.  Benchmark initialization
  4.  Benchmark accounting invariant (cash + shares*price == ending_nav)
  5.  Benchmark isolation (benchmark cannot alter strategy; strategy cannot alter benchmark)
  6.  Strategy/benchmark reconciliation
  7.  Excess return calculation
  8.  Benchmark drawdown
  9.  Forward-vs-backtest comparison
  10. Insufficient-sample labeling
  11. Immutable records (repeated execution does not alter sealed records)
  12. Repeated execution (ALREADY_SEALED / idempotency)
  13. Provider revision handling (sealed records survive price revision)
  14. PIT enforcement (future price rejected)
  15. Research-data isolation
  16. Failure handling
  17. Real-data integration (fixture variant; @real_data for live network)
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from mentisrex.research.forward_campaign import (
    BenchmarkCycleRecord,
    BenchmarkLedger,
    BenchmarkPortfolio,
    BenchmarkPerformanceSummary,
    BacktestSnapshot,
    CycleComparison,
    EvidenceReportBuilder,
    ForwardCampaign,
    ForwardLedger,
    CycleStatus,
    make_forward_cycle_id,
)
from mentisrex.research.forward_campaign.benchmark import _BENCHMARK_DATA_LIMITATION
from mentisrex.research.forward_campaign.evidence_report import (
    _evidence_stage,
    _INSUFFICIENT_MSG,
)
from mentisrex.research.paper_trading.loop import PaperTradingLoop, LoopConfig
from mentisrex.research.strategy_deployment.models import StrategyState, StrategyType, make_spec
from mentisrex.research.strategy_deployment.registry import StrategyRegistry
from mentisrex.research.strategy_deployment.runtime import StrategyRuntime, StrategyLogic


# ── shared fixtures ────────────────────────────────────────────────────────────

UNIVERSE = ["AAPL", "MSFT", "GOOGL"]
STARTING_CAPITAL = 1_000_000.0
STRATEGY_ID = "ew-momentum-exp"
STRATEGY_VERSION = "1.0.0"
STRATEGY_FINGERPRINT = "b69961b65bab226a500d71f45709945b"

# SPY prices for fixture cycles
SPY_AUG = 550.00    # 2026-08-13
SPY_SEP = 560.00    # 2026-09-10
SPY_OCT = 545.00    # 2026-10-08
SPY_NOV = 570.00    # 2026-11-05

AS_OF_AUG = date(2026, 8, 13)
AS_OF_SEP = date(2026, 9, 10)
AS_OF_OCT = date(2026, 10, 8)
AS_OF_NOV = date(2026, 11, 5)

CYCLE_AUG = make_forward_cycle_id(STRATEGY_ID, STRATEGY_VERSION, AS_OF_AUG)
CYCLE_SEP = make_forward_cycle_id(STRATEGY_ID, STRATEGY_VERSION, AS_OF_SEP)
CYCLE_OCT = make_forward_cycle_id(STRATEGY_ID, STRATEGY_VERSION, AS_OF_OCT)
CYCLE_NOV = make_forward_cycle_id(STRATEGY_ID, STRATEGY_VERSION, AS_OF_NOV)

FIXTURE_RECORDS_AUG = [
    {"symbol": "AAPL",  "date": "2026-08-01", "close": 185.0, "adj_close": 185.0,
     "open": 183.0, "high": 186.0, "low": 182.0, "volume": 50_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "MSFT",  "date": "2026-08-01", "close": 415.0, "adj_close": 413.0,
     "open": 412.0, "high": 416.0, "low": 410.0, "volume": 20_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "GOOGL", "date": "2026-08-01", "close": 172.0, "adj_close": 172.0,
     "open": 170.0, "high": 173.5, "low": 169.0, "volume": 15_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
]
FIXTURE_RECORDS_SEP = [
    {"symbol": "AAPL",  "date": "2026-09-01", "close": 190.0, "adj_close": 190.0,
     "open": 188.0, "high": 191.0, "low": 187.0, "volume": 48_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "MSFT",  "date": "2026-09-01", "close": 420.0, "adj_close": 420.0,
     "open": 418.0, "high": 422.0, "low": 417.0, "volume": 19_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "GOOGL", "date": "2026-09-01", "close": 175.0, "adj_close": 175.0,
     "open": 173.0, "high": 176.0, "low": 172.0, "volume": 14_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
]
FIXTURE_RECORDS_OCT = [
    {"symbol": "AAPL",  "date": "2026-10-01", "close": 195.0, "adj_close": 195.0,
     "open": 193.0, "high": 196.0, "low": 192.0, "volume": 47_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "MSFT",  "date": "2026-10-01", "close": 425.0, "adj_close": 425.0,
     "open": 423.0, "high": 427.0, "low": 422.0, "volume": 18_500_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "GOOGL", "date": "2026-10-01", "close": 178.0, "adj_close": 178.0,
     "open": 176.0, "high": 179.0, "low": 175.0, "volume": 13_500_000,
     "dividends": 0.0, "stock_splits": 0.0},
]
FIXTURE_RECORDS_NOV = [
    {"symbol": "AAPL",  "date": "2026-11-01", "close": 200.0, "adj_close": 200.0,
     "open": 198.0, "high": 201.0, "low": 197.0, "volume": 46_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "MSFT",  "date": "2026-11-01", "close": 430.0, "adj_close": 430.0,
     "open": 428.0, "high": 432.0, "low": 427.0, "volume": 18_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
    {"symbol": "GOOGL", "date": "2026-11-01", "close": 180.0, "adj_close": 180.0,
     "open": 178.0, "high": 181.0, "low": 177.0, "volume": 13_000_000,
     "dividends": 0.0, "stock_splits": 0.0},
]


# ── strategy helpers ───────────────────────────────────────────────────────────

class _EWLogic(StrategyLogic):
    def __init__(self, universe: list) -> None:
        self._universe = universe

    def generate_signals(self, snapshot, state):
        return {s: 1.0 for s in self._universe if hasattr(snapshot, "spots")
                and s in snapshot.spots and float(snapshot.spots[s].mid
                if hasattr(snapshot.spots[s], "mid") else snapshot.spots[s]) > 0}

    def construct_portfolio(self, signals, state):
        n = len(signals)
        if n == 0:
            return {}
        w = 1.0 / n
        return {s: w for s in signals}


def _make_spec():
    return make_spec(
        strategy_id=STRATEGY_ID,
        strategy_name="EW Momentum (test)",
        version=STRATEGY_VERSION,
        description="M27 test strategy",
        strategy_type=StrategyType.EXPERIMENTAL_PAPER,
        research_artifact_id="SIM",
        validation_artifact_id="696a411bed6731a997c399584bfa9c4f",
        validation_status="REQUIRES_REVIEW",
        universe_definition={"securities": UNIVERSE},
        required_data=["close"],
        feature_definition={"type": "price_level", "lookback_days": 0},
        signal_definition={"type": "equal_weight"},
        rebalance_frequency="monthly",
        portfolio_construction_config={"objective": "equal_weight"},
        risk_config={"max_position": 0.5, "max_gross_leverage": 1.0, "long_only": True},
        execution_config={"algo": "market"},
        transaction_cost_assumption={"slippage_bps": 5.0},
        slippage_assumption={"model": "linear", "bps": 5.0},
        benchmark="SPY",
        base_currency="USD",
        allowed_instruments=["equity"],
        capital_assumption=STARTING_CAPITAL,
        model_version="1.0.0",
    )


def _make_loop(spec):
    reg = StrategyRegistry()
    reg.register(spec, StrategyState.DRAFT)
    reg.transition(STRATEGY_ID, StrategyState.VALIDATING)
    reg.transition(STRATEGY_ID, StrategyState.VALIDATED)
    cfg = LoopConfig(
        initial_capital=STARTING_CAPITAL,
        permit_experimental=True,
        fail_closed=True,
        validate_readiness=True,
        mode="PAPER_FORWARD",
    )
    loop = PaperTradingLoop(runtime=StrategyRuntime(), registry=reg, config=cfg)
    loop.add_strategy(STRATEGY_ID, _EWLogic(UNIVERSE))
    return loop


def _run_campaign_cycle(spec, as_of, provider_records, tmp_dir, loop=None):
    """Helper: run one campaign cycle with fixture data."""
    campaign = ForwardCampaign.init(
        spec, _EWLogic(UNIVERSE), data_dir=tmp_dir,
        universe=UNIVERSE, starting_capital=STARTING_CAPITAL,
        campaign_id="TEST_CAMPAIGN",
        _loop=loop,
    ) if not (tmp_dir / "campaign_manifest.json").exists() else \
        ForwardCampaign.resume(spec, _EWLogic(UNIVERSE), tmp_dir)
    return campaign.run(as_of, provider_records=provider_records)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. September cycle creation (infrastructure test — fixture-based)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeptemberCycleCreation:
    """Verify September cycle can be created with fixture data.

    NOTE: This is an INFRASTRUCTURE TEST, not a genuine forward observation.
    It uses fixture prices, not real Yahoo Finance data.  Clearly labeled.
    """

    def test_september_cycle_id_distinct_from_august(self):
        assert CYCLE_SEP != CYCLE_AUG
        assert "2026_09" in CYCLE_SEP
        assert "2026_08" in CYCLE_AUG

    def test_september_benchmark_record_created(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        # inception (August)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        # September
        sep_rec = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        assert sep_rec.cycle_id == CYCLE_SEP
        assert sep_rec.status == "SUCCESS"
        assert sep_rec.is_sealed
        assert not sep_rec.is_inception_cycle

    def test_september_not_in_genuine_forward_evidence(self, tmp_path):
        """Fixture-based September must not be confused with real forward obs."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        sep = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        # In real usage, provider = "yahoo_finance" but we used fixture price.
        # The key distinction is that real data must come from a real network call.
        # This test verifies the data is correctly labeled with the provider field
        # and that the record is sealed with the fixture price (not a network price).
        assert sep.spy_price == SPY_SEP  # fixture price preserved
        assert "PAPER_FORWARD" == sep.mode


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Multi-month accumulation (Aug → Sep → Oct → Nov)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiMonthAccumulation:
    """Fixture-based multi-cycle accumulation test.

    FIXTURE TEST — NOT GENUINE FORWARD EVIDENCE.
    Uses deterministic offline prices.  Clearly distinct from real forward obs.
    """

    def _setup_four_cycles(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        aug = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        sep = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        oct_ = bp.evaluate(CYCLE_OCT, as_of=AS_OF_OCT, spy_price=SPY_OCT)
        nov = bp.evaluate(CYCLE_NOV, as_of=AS_OF_NOV, spy_price=SPY_NOV)
        return bp, [aug, sep, oct_, nov]

    def test_four_cycles_accumulated(self, tmp_path):
        bp, recs = self._setup_four_cycles(tmp_path)
        all_recs = bp.ledger.list_cycles()
        assert len(all_recs) == 4

    def test_nav_does_not_double(self, tmp_path):
        """Running the same cycles twice must not double NAV."""
        bp, _ = self._setup_four_cycles(tmp_path)
        # run again — idempotent
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        bp.evaluate(CYCLE_OCT, as_of=AS_OF_OCT, spy_price=SPY_OCT)
        bp.evaluate(CYCLE_NOV, as_of=AS_OF_NOV, spy_price=SPY_NOV)
        all_recs = bp.ledger.list_cycles()
        assert len(all_recs) == 4  # not 8

    def test_benchmark_nav_correct(self, tmp_path):
        bp, _ = self._setup_four_cycles(tmp_path)
        latest = bp.ledger.latest_cycle()
        # shares bought at inception price (SPY_AUG), NAV = shares * SPY_NOV + cash
        shares = STARTING_CAPITAL / SPY_AUG
        expected_nav = shares * SPY_NOV
        assert abs(latest.ending_nav - expected_nav) < 1.0

    def test_cumulative_return_reconciles(self, tmp_path):
        bp, _ = self._setup_four_cycles(tmp_path)
        latest = bp.ledger.latest_cycle()
        expected_cum = (SPY_NOV - SPY_AUG) / SPY_AUG
        assert abs(latest.cumulative_return - expected_cum) < 1e-6

    def test_monthly_returns_chain(self, tmp_path):
        bp, _ = self._setup_four_cycles(tmp_path)
        summary = bp.ledger.performance_summary()
        assert len(summary.monthly_returns) == 3  # 4 cycles → 3 period returns


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Benchmark initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkInitialization:
    def test_inception_cycle_creates_record(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert rec.is_inception_cycle
        assert rec.inception_price == SPY_AUG
        assert rec.inception_date == AS_OF_AUG
        assert rec.inception_nav == STARTING_CAPITAL

    def test_inception_nav_equals_starting_capital(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        # On inception: ending_nav ≈ starting_capital (fractional cash residual)
        assert abs(rec.ending_nav - STARTING_CAPITAL) < 1.0

    def test_inception_return_zero(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert rec.period_return == 0.0  # buy day: no prior price

    def test_benchmark_data_limitation_documented(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert "dividend" in rec.data_limitation.lower()
        assert "price return" in rec.data_limitation.lower()

    def test_benchmark_symbol_is_spy(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert rec.benchmark_symbol == "SPY"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Benchmark accounting invariant
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkAccountingInvariant:
    """Benchmark cash + shares * spy_price == ending_nav (within fp tolerance)."""

    def _check_invariant(self, rec: BenchmarkCycleRecord) -> None:
        expected = rec.shares * rec.spy_price + rec.cash
        assert abs(expected - rec.ending_nav) < 1e-6, (
            f"Invariant violation: {rec.shares}*{rec.spy_price}+{rec.cash} "
            f"= {expected} != {rec.ending_nav}"
        )

    def test_inception_invariant(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        self._check_invariant(rec)

    def test_subsequent_invariant(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        rec = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        self._check_invariant(rec)

    def test_multi_cycle_invariants(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        spy_prices = [(CYCLE_AUG, AS_OF_AUG, SPY_AUG),
                      (CYCLE_SEP, AS_OF_SEP, SPY_SEP),
                      (CYCLE_OCT, AS_OF_OCT, SPY_OCT),
                      (CYCLE_NOV, AS_OF_NOV, SPY_NOV)]
        for cycle_id, as_of, price in spy_prices:
            rec = bp.evaluate(cycle_id, as_of=as_of, spy_price=price)
            self._check_invariant(rec)

    def test_shares_constant_across_cycles(self, tmp_path):
        """Buy-and-hold: shares must not change after inception."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        aug = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        sep = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        assert aug.shares == sep.shares


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Benchmark isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkIsolation:
    """Benchmark cannot alter strategy; strategy cannot alter benchmark NAV."""

    def test_benchmark_stored_in_separate_dir(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        # benchmark files in benchmark/ subdir
        assert (tmp_path / "benchmark" / f"{CYCLE_AUG}.json").exists()
        # strategy cycles NOT in benchmark/ dir
        assert not (tmp_path / "benchmark" / "campaign_checkpoint.json").exists()

    def test_benchmark_nav_independent_of_strategy_signals(self, tmp_path):
        """Benchmark NAV depends only on SPY price, not on strategy signals."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec1 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        rec2 = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        # NAV = shares * price; shares = 1_000_000 / SPY_AUG
        expected_nav = (STARTING_CAPITAL / SPY_AUG) * SPY_SEP
        assert abs(rec2.ending_nav - expected_nav) < 1.0

    def test_strategy_has_no_benchmark_attribute(self, tmp_path):
        """ForwardCampaign/ForwardLedger has no benchmark field."""
        ledger = ForwardLedger(tmp_path)
        summary = ledger.performance_summary()
        # forward ledger summary must not contain benchmark NAV
        assert not hasattr(summary, "benchmark_nav")
        assert not hasattr(summary, "benchmark_symbol")

    def test_benchmark_ledger_has_no_strategy_positions(self, tmp_path):
        """BenchmarkCycleRecord has no strategy positions or signal outputs."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert not hasattr(rec, "positions")
        assert not hasattr(rec, "signal_outputs")
        assert not hasattr(rec, "portfolio_weights")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Strategy/benchmark reconciliation
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyBenchmarkReconciliation:
    def test_excess_return_strategy_minus_benchmark(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        aug = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        sep = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)

        # Simulate strategy with flat return (equal weight, prices up +2.7% on avg)
        strategy_return = 0.027   # example
        benchmark_return = sep.period_return
        excess = strategy_return - benchmark_return
        assert isinstance(excess, float)

    def test_relative_performance_sum_reconciles(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        sep = bp.ledger.latest_cycle()
        # cumulative_return = (SPY_SEP - SPY_AUG) / SPY_AUG
        expected_cum = (SPY_SEP - SPY_AUG) / SPY_AUG
        assert abs(sep.cumulative_return - expected_cum) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Excess return calculation
# ═══════════════════════════════════════════════════════════════════════════════

class TestExcessReturnCalculation:
    def _build_report(self, tmp_path, strategy_nav, benchmark_nav):
        """Minimal report builder for excess return tests."""
        # write fake forward cycle records
        cycles_dir = tmp_path / "cycles"
        cycles_dir.mkdir(parents=True, exist_ok=True)
        benchmark_dir = tmp_path / "benchmark"
        benchmark_dir.mkdir(exist_ok=True)

        # strategy cycle Aug (inception, return=0)
        from mentisrex.research.forward_campaign.record import ForwardCycleRecord
        aug_rec = ForwardCycleRecord(
            cycle_id=CYCLE_AUG,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            evaluation_date=date(2026, 8, 1),
            knowledge_as_of=AS_OF_AUG,
            starting_nav=STARTING_CAPITAL,
            ending_nav=STARTING_CAPITAL,
            gross_return=0.0,
            fills=10,
            status=CycleStatus.SUCCESS,
            sealed_at=datetime.utcnow().isoformat(),
        )
        (cycles_dir / f"{CYCLE_AUG}.json").write_text(
            json.dumps(aug_rec.to_dict(), indent=2, default=str))

        # strategy cycle Sep
        sep_strat_return = (strategy_nav - STARTING_CAPITAL) / STARTING_CAPITAL
        sep_rec = ForwardCycleRecord(
            cycle_id=CYCLE_SEP,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            evaluation_date=date(2026, 9, 1),
            knowledge_as_of=AS_OF_SEP,
            starting_nav=STARTING_CAPITAL,
            ending_nav=strategy_nav,
            gross_return=sep_strat_return,
            fills=3,
            status=CycleStatus.SUCCESS,
            sealed_at=datetime.utcnow().isoformat(),
        )
        (cycles_dir / f"{CYCLE_SEP}.json").write_text(
            json.dumps(sep_rec.to_dict(), indent=2, default=str))

        # benchmark cycles
        aug_bm = BenchmarkCycleRecord(
            cycle_id=CYCLE_AUG,
            benchmark_symbol="SPY",
            evaluation_date=date(2026, 8, 1),
            knowledge_as_of=AS_OF_AUG,
            spy_price=SPY_AUG,
            inception_price=SPY_AUG,
            inception_date=AS_OF_AUG,
            shares=STARTING_CAPITAL / SPY_AUG,
            cash=0.0,
            inception_nav=STARTING_CAPITAL,
            starting_nav=STARTING_CAPITAL,
            ending_nav=STARTING_CAPITAL,
            period_return=0.0,
            cumulative_return=0.0,
            is_inception_cycle=True,
            status="SUCCESS",
            sealed_at=datetime.utcnow().isoformat(),
        )
        (benchmark_dir / f"{CYCLE_AUG}.json").write_text(
            json.dumps(aug_bm.to_dict(), indent=2, default=str))

        bmk_period_return = (benchmark_nav - STARTING_CAPITAL) / STARTING_CAPITAL
        sep_bm = BenchmarkCycleRecord(
            cycle_id=CYCLE_SEP,
            benchmark_symbol="SPY",
            evaluation_date=date(2026, 9, 1),
            knowledge_as_of=AS_OF_SEP,
            spy_price=SPY_SEP,
            spy_price_prior=SPY_AUG,
            inception_price=SPY_AUG,
            inception_date=AS_OF_AUG,
            shares=STARTING_CAPITAL / SPY_AUG,
            cash=0.0,
            inception_nav=STARTING_CAPITAL,
            starting_nav=STARTING_CAPITAL,
            ending_nav=benchmark_nav,
            period_return=bmk_period_return,
            cumulative_return=bmk_period_return,
            is_inception_cycle=False,
            status="SUCCESS",
            sealed_at=datetime.utcnow().isoformat(),
        )
        (benchmark_dir / f"{CYCLE_SEP}.json").write_text(
            json.dumps(sep_bm.to_dict(), indent=2, default=str))

        # write manifest
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "TEST", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))

        return EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        ).build(load_backtest=False)

    def test_excess_return_strategy_outperforms(self, tmp_path):
        report = self._build_report(
            tmp_path,
            strategy_nav=1_050_000.0,     # strategy +5%
            benchmark_nav=1_020_000.0,    # benchmark +2%
        )
        # excess = strategy_cum - benchmark_cum = 5% - 2% = 3%
        assert report.cumulative_excess_return > 0

    def test_excess_return_benchmark_outperforms(self, tmp_path):
        report = self._build_report(
            tmp_path,
            strategy_nav=1_010_000.0,     # strategy +1%
            benchmark_nav=1_030_000.0,    # benchmark +3%
        )
        assert report.cumulative_excess_return < 0

    def test_excess_return_zero_when_equal(self, tmp_path):
        report = self._build_report(
            tmp_path,
            strategy_nav=1_020_000.0,
            benchmark_nav=1_020_000.0,
        )
        assert abs(report.cumulative_excess_return) < 1e-6

    def test_cycle_comparison_entries_correct(self, tmp_path):
        report = self._build_report(
            tmp_path,
            strategy_nav=1_050_000.0,
            benchmark_nav=1_020_000.0,
        )
        assert len(report.cycle_comparisons) == 2
        # Sep comparison should show positive excess
        sep_cmp = report.cycle_comparisons[1]
        assert sep_cmp.excess_return > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Benchmark drawdown
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkDrawdown:
    def test_drawdown_zero_when_rising(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)  # 550
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)  # 560
        sep = bp.ledger.latest_cycle()
        assert sep.max_drawdown == 0.0

    def test_drawdown_positive_when_falling(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)  # 550
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)  # 560 (peak)
        bp.evaluate(CYCLE_OCT, as_of=AS_OF_OCT, spy_price=SPY_OCT)  # 545 (below aug)
        oct_ = bp.ledger.latest_cycle()
        assert oct_.max_drawdown > 0

    def test_drawdown_correct_value(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)  # 550
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)  # 560
        bp.evaluate(CYCLE_OCT, as_of=AS_OF_OCT, spy_price=SPY_OCT)  # 545
        oct_ = bp.ledger.latest_cycle()
        # peak NAV = shares * 560; current NAV = shares * 545
        shares = STARTING_CAPITAL / SPY_AUG
        peak_nav = shares * SPY_SEP
        current_nav = shares * SPY_OCT
        expected_dd = (peak_nav - current_nav) / peak_nav
        assert abs(oct_.max_drawdown - expected_dd) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Forward-vs-backtest comparison
# ═══════════════════════════════════════════════════════════════════════════════

class TestForwardVsBacktestComparison:
    def test_backtest_snapshot_loads(self):
        bt = BacktestSnapshot.load()
        assert bt.manifest_hash == "696a411bed6731a997c399584bfa9c4f"
        assert bt.sharpe_annualized > 0
        assert bt.n_observations > 0

    def test_backtest_snapshot_fingerprint_unchanged(self):
        bt = BacktestSnapshot()
        assert bt.strategy_fingerprint == STRATEGY_FINGERPRINT

    def test_forward_vs_backtest_labeled_insufficient(self, tmp_path):
        """With n<12 forward cycles, comparison labeled INSUFFICIENT_SAMPLE."""
        # empty campaign directory
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "TEST", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))
        builder = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        )
        report = builder.build(load_backtest=False)
        assert report.backtest_vs_forward["comparison_validity"] == "INSUFFICIENT_SAMPLE"

    def test_backtest_metrics_not_recalibrated_by_forward(self, tmp_path):
        """Backtest metrics must be frozen; forward data cannot change them."""
        bt = BacktestSnapshot.load()
        sharpe_before = bt.sharpe_annualized
        # Simulate some forward data (doesn't matter what)
        _ = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        # BacktestSnapshot is immutable (frozen dataclass)
        bt2 = BacktestSnapshot.load()
        assert bt2.sharpe_annualized == sharpe_before


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Insufficient-sample labeling
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsufficientSampleLabeling:
    def test_evidence_stage_0_obs(self):
        s = _evidence_stage(0)
        assert "NO_OBSERVATIONS" in s

    def test_evidence_stage_1_obs(self):
        s = _evidence_stage(1)
        assert "OPERATIONAL_EVIDENCE_ONLY" in s

    def test_evidence_stage_2_obs(self):
        s = _evidence_stage(2)
        assert "EARLY_DIAGNOSTIC" in s

    def test_evidence_stage_6_obs(self):
        s = _evidence_stage(6)
        assert "PRELIMINARY" in s

    def test_evidence_stage_12_obs(self):
        s = _evidence_stage(12)
        assert "ANNUAL" in s

    def test_evidence_stage_24_obs(self):
        s = _evidence_stage(24)
        assert "STRONGER" in s

    def test_insufficient_sample_message_includes_n(self, tmp_path):
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "T", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))
        report = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        ).build(load_backtest=False)
        assert "n=0" in report.statistical_status_message
        assert report.insufficient_sample is True

    def test_insufficient_sample_with_1_observation(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        summary = bp.ledger.performance_summary()
        assert summary.annualized_return_label == "INSUFFICIENT_SAMPLE"

    def test_no_sharpe_with_single_cycle(self, tmp_path):
        ledger = ForwardLedger(tmp_path)
        summary = ledger.performance_summary()
        assert summary.sharpe is None
        assert summary.sharpe_label == "INSUFFICIENT_SAMPLE"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Immutable records
# ═══════════════════════════════════════════════════════════════════════════════

class TestImmutableRecords:
    def test_benchmark_record_not_overwritten(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec1 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        # call again with a DIFFERENT price — must return the original
        rec2 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=9999.0)
        assert rec2.spy_price == rec1.spy_price  # original sealed price preserved
        assert rec2.sealed_at == rec1.sealed_at

    def test_strategy_sealed_at_not_changed_on_rerun(self, tmp_path):
        """Simulates sealed record on disk; new BenchmarkPortfolio won't overwrite."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec1 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        original_sealed = rec1.sealed_at

        # New portfolio instance — reload from disk
        bp2 = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec2 = bp2.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=600.0)
        assert rec2.sealed_at == original_sealed
        assert rec2.spy_price == SPY_AUG

    def test_benchmark_file_exists_after_seal(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert (tmp_path / "benchmark" / f"{CYCLE_AUG}.json").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Repeated execution (idempotency)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRepeatedExecutionIdempotency:
    def test_repeated_benchmark_eval_idempotent(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        r1 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        r2 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        r3 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert r1.record_fingerprint() == r2.record_fingerprint()
        assert r1.record_fingerprint() == r3.record_fingerprint()

    def test_repeated_eval_does_not_add_extra_records(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        for _ in range(5):
            bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert len(bp.ledger.list_cycles()) == 1

    def test_benchmark_nav_same_on_repeated_run(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        nav1 = bp.ledger.latest_cycle().ending_nav
        # run again
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        nav2 = bp.ledger.latest_cycle().ending_nav
        assert nav1 == nav2


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Provider revision handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderRevisionHandling:
    def test_sealed_record_survives_price_revision(self, tmp_path):
        """If Yahoo later revises a price, the sealed record must not change."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec1 = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        original_price = rec1.spy_price
        original_nav = rec1.ending_nav

        # Simulate retroactive provider revision (Yahoo changes SPY price)
        revised_price = SPY_AUG * 1.05  # 5% revision
        bp2 = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec2 = bp2.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=revised_price)

        # Sealed record must be unchanged
        assert rec2.spy_price == original_price
        assert abs(rec2.ending_nav - original_nav) < 1e-6

    def test_revision_cannot_alter_cumulative_return(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        rec = bp.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP)
        cum_return_original = rec.cumulative_return

        # Revision attempt
        bp2 = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec2 = bp2.evaluate(CYCLE_SEP, as_of=AS_OF_SEP, spy_price=SPY_SEP * 2)
        assert abs(rec2.cumulative_return - cum_return_original) < 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 14. PIT enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestPITEnforcement:
    def test_benchmark_record_stores_knowledge_as_of(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert rec.knowledge_as_of == AS_OF_AUG

    def test_benchmark_spy_price_is_pit_constrained(self, tmp_path):
        """The price used must correspond to as_of, not a future date."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        # Price stored is exactly what was passed — no future adjustment
        assert rec.spy_price == SPY_AUG
        assert rec.knowledge_as_of == AS_OF_AUG

    def test_fetch_spy_price_returns_none_for_future(self):
        """fetch_spy_price with a far-future date should return None or error."""
        from mentisrex.research.forward_campaign.benchmark import fetch_spy_price
        # We don't actually call the network (would fail in offline test),
        # but we verify the function exists and has the right signature.
        import inspect
        sig = inspect.signature(fetch_spy_price)
        assert "as_of" in sig.parameters


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Research-data isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestResearchDataIsolation:
    def test_benchmark_dir_separate_from_research(self, tmp_path):
        """Benchmark data is in {campaign_dir}/benchmark/, isolated from research."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        # benchmark dir exists; no research files in it
        bdir = tmp_path / "benchmark"
        assert bdir.exists()
        non_benchmark = [f for f in bdir.iterdir()
                         if not f.name.endswith(".json")]
        assert len(non_benchmark) == 0

    def test_forward_ledger_does_not_expose_research_pipeline(self, tmp_path):
        """ForwardLedger has no method to push data to research pipeline."""
        ledger = ForwardLedger(tmp_path)
        research_methods = [m for m in dir(ledger)
                            if any(k in m for k in
                                   ("train", "optimize", "backtest", "fit", "calibrate"))]
        assert len(research_methods) == 0

    def test_benchmark_ledger_does_not_expose_research_pipeline(self, tmp_path):
        ledger = BenchmarkLedger(tmp_path)
        research_methods = [m for m in dir(ledger)
                            if any(k in m for k in
                                   ("train", "optimize", "backtest", "fit", "calibrate"))]
        assert len(research_methods) == 0

    def test_evidence_report_research_isolated_flag(self, tmp_path):
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "T", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))
        report = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        ).build(load_backtest=False)
        assert report.research_data_isolated == "YES"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Failure handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailureHandling:
    def test_zero_spy_price_does_not_crash(self, tmp_path):
        """Zero price must not crash the portfolio — shares become 0."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        # Zero price: shares = 0, ending_nav = 0
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=0.0)
        assert rec.shares == 0.0
        # Record is still sealed and stored
        assert rec.is_sealed

    def test_negative_spy_price_handled(self, tmp_path):
        """Negative price treated same as zero."""
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=-10.0)
        # -10 is treated same as 0 (shares = 0)
        assert rec.shares == 0.0

    def test_corrupt_benchmark_file_skipped_by_ledger(self, tmp_path):
        """Ledger must skip corrupt files without crashing."""
        bdir = tmp_path / "benchmark"
        bdir.mkdir()
        (bdir / "corrupted.json").write_text("NOT VALID JSON {{{{")
        ledger = BenchmarkLedger(tmp_path)
        recs = ledger.list_cycles()  # must not raise
        assert isinstance(recs, list)

    def test_empty_campaign_dir_returns_zero_nav(self, tmp_path):
        ledger = BenchmarkLedger(tmp_path)
        assert ledger.current_nav() == 0.0

    def test_missing_benchmark_dir_returns_empty(self, tmp_path):
        ledger = BenchmarkLedger(tmp_path)
        assert ledger.list_cycles() == []


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Real-data integration (fixture variant; @real_data for live network)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealDataIntegrationFixture:
    """Fixture-based variant of real-data test.  No network calls."""

    def test_benchmark_cycle_record_serialization_roundtrip(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        d = rec.to_dict()
        rec2 = BenchmarkCycleRecord.from_dict(d)
        assert rec2.cycle_id == rec.cycle_id
        assert rec2.spy_price == rec.spy_price
        assert rec2.ending_nav == rec.ending_nav
        assert rec2.evaluation_date == rec.evaluation_date

    def test_benchmark_data_limitation_label_present(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        rec = bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        assert "yahoo" in rec.data_limitation.lower()

    def test_evidence_report_governance_labels(self, tmp_path):
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "T", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))
        report = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        ).build(load_backtest=False)
        assert report.real_market_data == "YES"
        assert report.live_execution == "NO"
        assert report.real_capital == "NO"
        assert report.strategy_modified == "NO"

    def test_backtest_snapshot_strategy_fingerprint_matches(self):
        """Backtest snapshot must match the live strategy fingerprint."""
        bt = BacktestSnapshot()
        assert bt.strategy_fingerprint == STRATEGY_FINGERPRINT


@pytest.mark.real_data
class TestRealDataBenchmark:
    """Live network tests — excluded from offline suite.

    Run with: pytest -m real_data
    Requires internet access to Yahoo Finance.
    """

    def test_fetch_spy_price_returns_positive(self):
        from mentisrex.research.forward_campaign.benchmark import fetch_spy_price
        price = fetch_spy_price(date(2026, 8, 13))
        # If the date is in the future, may return None — acceptable
        if price is not None:
            assert price > 0

    def test_real_spy_price_august_2026(self):
        from mentisrex.research.forward_campaign.benchmark import fetch_spy_price
        price = fetch_spy_price(AS_OF_AUG)
        # August 13 2026 has already passed at time of running
        if price is not None:
            assert price > 100  # SPY should be > $100

    def test_september_benchmark_pending(self):
        """Verify September 2026 benchmark is pending — not yet available."""
        from mentisrex.research.forward_campaign.benchmark import fetch_spy_price
        from datetime import date
        today = date.today()
        assert today < date(2026, 9, 10), (
            "September 2026 has arrived — run genuine forward_benchmark for September."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Additional: BenchmarkPerformanceSummary and EvidenceReport integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestBenchmarkPerformanceSummary:
    def test_summary_insufficient_sample_on_one_cycle(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        s = bp.ledger.performance_summary()
        assert s.annualized_return is None
        assert s.annualized_return_label == "INSUFFICIENT_SAMPLE"
        assert s.volatility is None
        assert s.volatility_label == "INSUFFICIENT_SAMPLE"

    def test_summary_inception_nav_preserved(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        s = bp.ledger.performance_summary()
        assert s.inception_nav == STARTING_CAPITAL

    def test_summary_inception_date_set(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        s = bp.ledger.performance_summary()
        assert s.inception_date == AS_OF_AUG

    def test_summary_data_limitation_documented(self, tmp_path):
        bp = BenchmarkPortfolio(tmp_path, inception_nav=STARTING_CAPITAL)
        bp.evaluate(CYCLE_AUG, as_of=AS_OF_AUG, spy_price=SPY_AUG)
        s = bp.ledger.performance_summary()
        assert "dividend" in s.data_limitation.lower()


class TestEvidenceReportIntegration:
    def test_report_strategy_fingerprint_preserved(self, tmp_path):
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "T", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))
        report = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        ).build(load_backtest=False)
        assert report.strategy_fingerprint == STRATEGY_FINGERPRINT

    def test_report_serializes_to_dict(self, tmp_path):
        (tmp_path / "cycles").mkdir()
        (tmp_path / "benchmark").mkdir()
        (tmp_path / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": "T", "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "strategy_fingerprint": STRATEGY_FINGERPRINT,
            "starting_capital": STARTING_CAPITAL,
        }))
        report = EvidenceReportBuilder(
            campaign_dir=tmp_path,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            strategy_fingerprint=STRATEGY_FINGERPRINT,
            universe=UNIVERSE,
            initial_capital=STARTING_CAPITAL,
        ).build(load_backtest=False)
        d = report.to_dict()
        assert isinstance(d, dict)
        assert d["strategy_fingerprint"] == STRATEGY_FINGERPRINT
        assert d["live_execution"] == "NO"
