"""Regression tests for the two verified JT-campaign defects.

G1 — evaluation harness: an in-sample drawdown halt must not zero the OOS window.
G2 — dataset isolation: toy loaders must not touch the production DB, and
     reproductions must read only validated (adequate-history) series.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aurelius.backtesting.config import BacktestConfig
from aurelius.market_data.storage.duckdb_store import DuckDBStore
from aurelius.market_data.storage.isolation import (
    MIN_VALIDATED_BARS,
    PRODUCTION_DB,
    TOY_DB,
    ProductionIsolationError,
    assert_not_production,
    validated_universe_filter,
)
from aurelius.research.runner import synth_bars
from aurelius.research.templates import FactorStrategy
from aurelius.research.validation import run_backtest, train_test

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


def test_g2_validated_filter_excludes_truncated_toy_series():
    """A short synthetic series (like the 520-bar toy residue) is excluded from a
    reproduction universe, while an adequate-history real series is admitted."""
    store = DuckDBStore(":memory:")
    t0 = datetime(2015, 1, 1, tzinfo=UTC)
    real = [_bar_row("REAL", t0 + timedelta(days=i), 100 + i * 0.1)
            for i in range(MIN_VALIDATED_BARS + 5)]
    toy = [_bar_row("TOY", t0 + timedelta(days=i), 216.0) for i in range(10)]
    store.write_bars(real + toy)

    rows = store.query(f"SELECT DISTINCT symbol FROM ohlcv WHERE "
                       f"{validated_universe_filter()}")
    syms = {r["symbol"] for r in rows}
    store.close()
    assert "REAL" in syms
    assert "TOY" not in syms
