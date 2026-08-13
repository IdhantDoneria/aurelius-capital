"""Regression tests for the two verified JT-campaign defects.

G1 — evaluation harness: an in-sample drawdown halt must not zero the OOS window.
G2 — dataset isolation: toy loaders must not touch the production DB, and
     reproductions must read only validated (adequate-history) series.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mentisrex.backtesting.config import BacktestConfig
from mentisrex.market_data.storage.duckdb_store import DuckDBStore
from mentisrex.market_data.storage.isolation import (
    MIN_VALIDATED_BARS,
    PRODUCTION_DB,
    TOY_DB,
    ProductionIsolationError,
    assert_not_production,
    validated_universe_filter,
)
from mentisrex.research.runner import synth_bars
from mentisrex.research.templates import FactorStrategy
from mentisrex.research.validation import run_backtest, train_test

# ── G1 ──────────────────────────────────────────────────────────────────────


def _factory():
    return FactorStrategy(lookback=20, quantile=0.2, rebalance_days=10, allow_short=True)


def test_g1_is_halt_does_not_zero_oos():
    """Tiny drawdown halt trips IN-SAMPLE, yet OOS still trades and its metrics
    equal an independent OOS-only backtest — proving IS and OOS run on separate
    engine state (the fix). Under the old shared-engine path the IS halt would
    have stopped the whole run before OOS, leaving OOS with zero trades."""
    bars = synth_bars(["AAA", "BBB", "CCC", "DDD", "EEE"], days=300, seed=3,
                      drift=0.001, vol=0.02)
    # Halt so small it necessarily fires inside the IS window.
    cfg = BacktestConfig(max_drawdown_halt=Decimal("0.005"),
                         max_position_pct=Decimal("0.05"))
    ts = sorted({b.timestamp for b in bars})
    cut = ts[int(len(ts) * 0.7)]
    oos_bars = [b for b in bars if b.timestamp >= cut]

    is_m, oos_m = train_test(_factory, bars, cfg, train_frac=0.7)
    oos_only = run_backtest(_factory, oos_bars, cfg)

    # OOS executed independently despite the IS halt.
    assert oos_m.num_trades > 0
    # OOS is byte-for-byte the independent OOS run — no bleed from IS state.
    assert oos_m.num_trades == oos_only.num_trades
    assert oos_m.total_return == pytest.approx(oos_only.total_return, abs=1e-9)


def test_g1_oos_is_independent_of_is_config_state():
    """OOS metrics are invariant to how far the IS run got: whether IS halts
    early (tiny limit) or runs full (loose limit), the OOS result is identical
    to a standalone OOS backtest under that same config."""
    bars = synth_bars(["AAA", "BBB", "CCC", "DDD", "EEE"], days=300, seed=3,
                      drift=0.001, vol=0.02)
    ts = sorted({b.timestamp for b in bars})
    cut = ts[int(len(ts) * 0.7)]
    oos_bars = [b for b in bars if b.timestamp >= cut]

    for halt in ("0.005", "0.60"):
        cfg = BacktestConfig(max_drawdown_halt=Decimal(halt),
                             max_position_pct=Decimal("0.05"))
        _, oos_m = train_test(_factory, bars, cfg, train_frac=0.7)
        oos_only = run_backtest(_factory, oos_bars, cfg)
        assert oos_m.num_trades == oos_only.num_trades
        assert oos_m.total_return == pytest.approx(oos_only.total_return, abs=1e-9)


# ── G2 ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [PRODUCTION_DB, "data/analytics.duckdb", "./data/../data/analytics.duckdb"],
)
def test_g2_toy_loader_cannot_target_production(path):
    with pytest.raises(ProductionIsolationError):
        assert_not_production(path)


def test_g2_toy_db_is_allowed():
    assert_not_production(TOY_DB)  # isolated store — must not raise
    assert_not_production(":memory:")


def _bar_row(sym: str, ts: datetime, price: float) -> dict:
    p = Decimal(str(price))
    return {
        "symbol": sym, "timestamp": ts, "frequency": "1d",
        "open": p, "high": p, "low": p, "close": p,
        "volume": Decimal("1000"), "vwap": p, "trade_count": 1,
        "quality_score": None, "source": "test",
    }


# Real contamination signature measured on production analytics.duckdb.
TOY_BARS = 520          # every known toy series carries exactly 520 bars
LEGIT_MIN_BARS = 2201   # smallest real US/India series


def _seed(store: DuckDBStore, symbol: str, n_bars: int, price: float) -> None:
    t0 = datetime(2015, 1, 1, tzinfo=UTC)
    store.write_bars(
        [_bar_row(symbol, t0 + timedelta(days=i), price) for i in range(n_bars)]
    )


def test_g2_threshold_sits_between_toy_and_legit():
    """The gate must reject the 520-bar toy signature and admit real data."""
    assert TOY_BARS < MIN_VALIDATED_BARS <= LEGIT_MIN_BARS


def test_g2_validated_filter_rejects_real_toy_signature():
    """Actual contaminated tickers (real names, real 520-bar signature) are
    rejected, while legitimate production symbols remain admitted. Replaces the
    earlier 10-bar stub that never exercised the true contamination length."""
    store = DuckDBStore(":memory:")
    toy_tickers = ["GE", "JPM", "KO", "META", "MSFT", "NVDA", "PG", "T", "XOM"]
    for t in toy_tickers:
        _seed(store, t, TOY_BARS, 216.0)          # 520-bar synthetic residue
    _seed(store, "REALCO", LEGIT_MIN_BARS, 100.0)  # legitimate production series

    rows = store.query(
        f"SELECT DISTINCT symbol FROM ohlcv WHERE {validated_universe_filter()}"
    )
    admitted = {r["symbol"] for r in rows}
    store.close()

    assert admitted == {"REALCO"}, f"toy leaked through gate: {admitted}"
    assert not (set(toy_tickers) & admitted)


def test_g2_boundary_520_rejected_521_admitted():
    """Tight boundary: a 520-bar series is rejected, a 521-bar series is admitted."""
    store = DuckDBStore(":memory:")
    _seed(store, "AT520", TOY_BARS, 50.0)
    _seed(store, "AT521", TOY_BARS + 1, 50.0)
    rows = store.query(
        f"SELECT DISTINCT symbol FROM ohlcv WHERE {validated_universe_filter()}"
    )
    admitted = {r["symbol"] for r in rows}
    store.close()
    assert "AT520" not in admitted
    assert "AT521" in admitted
