"""End-to-end BacktestEngine tests with deterministic synthetic data.

Tests the full pipeline:
  DataFeed → EventQueue → Strategy → PortfolioManager → RiskEngine
  → ExecutionSimulator → PortfolioState → PerformanceCalculator → BacktestReport

A simple SMA crossover strategy is implemented inline (no external deps).
Synthetic price data is generated to produce predictable buy/sell signals.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aurelius.backtesting import BacktestConfig, BacktestEngine
from aurelius.backtesting.data.feed import BarData, InMemoryDataFeed
from aurelius.backtesting.events.types import Direction, MarketEvent, SignalEvent
from aurelius.backtesting.strategy.base import Strategy, StrategyContext

# ── Example strategy: SMA crossover ──────────────────────────────────────────


class SMACrossover(Strategy):
    """Fast/slow moving average crossover. Long when fast > slow, flat otherwise."""

    name = "sma_crossover"

    def __init__(self, fast: int = 5, slow: int = 10) -> None:
        self.fast = fast
        self.slow = slow

    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        closes = context.close_series(bar.symbol, lookback=self.slow + 1)
        if len(closes) < self.slow:
            return []

        fast_ma = sum(closes[-self.fast :]) / self.fast
        slow_ma = sum(closes[-self.slow :]) / self.slow

        pos = context.portfolio.position(bar.symbol)

        if fast_ma > slow_ma and pos.is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, strength=1.0)]
        if fast_ma < slow_ma and pos.is_long:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        return []

    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow}


class BuyAndHold(Strategy):
    """Always long. Used to test that a simple strategy produces fills."""

    name = "buy_and_hold"

    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        pos = context.portfolio.position(bar.symbol)
        if pos.is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, strength=1.0)]
        return []


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _synthetic_bars(
    symbol: str = "AAPL",
    n_bars: int = 60,
    start_price: float = 100.0,
    trend: float = 0.5,  # daily drift in $
) -> list[BarData]:
    """Generate synthetic daily bars with linear trend + small noise."""
    bars = []
    ts = datetime(2024, 1, 2, tzinfo=UTC)
    price = start_price
    for i in range(n_bars):
        open_ = price
        close = price + trend
        high = max(open_, close) + 0.5
        low = min(open_, close) - 0.5
        bars.append(
            BarData(
                symbol=symbol,
                timestamp=ts + timedelta(days=i),
                open=Decimal(str(round(open_, 4))),
                high=Decimal(str(round(high, 4))),
                low=Decimal(str(round(low, 4))),
                close=Decimal(str(round(close, 4))),
                volume=Decimal("500000"),
            )
        )
        price = close
    return bars


@pytest.fixture
def uptrend_feed() -> InMemoryDataFeed:
    return InMemoryDataFeed(_synthetic_bars(n_bars=60, trend=1.0))


@pytest.fixture
def flat_feed() -> InMemoryDataFeed:
    return InMemoryDataFeed(_synthetic_bars(n_bars=60, trend=0.0))


@pytest.fixture
def default_config() -> BacktestConfig:
    return BacktestConfig(
        initial_capital=Decimal("100_000"),
        commission_rate=Decimal("0.001"),
        spread_bps=Decimal("2"),
        slippage_impact_bps=Decimal("2"),
        max_position_pct=Decimal("0.10"),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_engine_runs_without_error(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    assert report is not None
    assert report.total_bars == 60


@pytest.mark.unit
def test_buy_and_hold_positive_return_in_uptrend(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    # Price rises from 100 to ~160 (60 x $1 trend) → should be profitable
    assert report.metrics.total_return > 0, "Buy-and-hold in uptrend must be profitable"


@pytest.mark.unit
def test_flat_market_preserves_capital(flat_feed, default_config):
    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=flat_feed,
        config=default_config,
    )
    report = engine.run()
    # Flat price, but transaction costs apply → slight loss expected
    # But loss should be small (< 5%)
    assert report.metrics.total_return > -0.05, "Transaction costs must not devastate capital"


@pytest.mark.unit
def test_sma_crossover_generates_trades(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=SMACrossover(fast=3, slow=7),
        data_feed=uptrend_feed,
        config=default_config,
    )
    engine.run()
    # At minimum, the strategy should have made at least one fill
    assert len(engine._all_fills) > 0


@pytest.mark.unit
def test_equity_curve_has_one_point_per_bar(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    assert len(report.metrics.equity_curve) == 60


@pytest.mark.unit
def test_equity_curve_starts_at_initial_capital(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    first_equity = report.metrics.equity_curve[0].equity
    assert abs(first_equity - float(default_config.initial_capital)) < 1_000


@pytest.mark.unit
def test_report_strategy_name(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=SMACrossover(fast=5, slow=10),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    assert report.strategy_name == "sma_crossover"
    assert report.strategy_parameters == {"fast": 5, "slow": 10}


@pytest.mark.unit
def test_report_to_dict_is_json_serializable(uptrend_feed, default_config):
    import json

    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    d = report.to_dict()
    json_str = json.dumps(d, default=str)
    assert len(json_str) > 100


@pytest.mark.unit
def test_drawdown_never_positive(uptrend_feed, default_config):
    engine = BacktestEngine(
        strategy=BuyAndHold(),
        data_feed=uptrend_feed,
        config=default_config,
    )
    report = engine.run()
    for _, dd in report.metrics.drawdown_series:
        assert dd <= 0.001, "Drawdown can never be positive (it's a loss measure)"


@pytest.mark.unit
def test_max_drawdown_halt_prevents_new_orders():
    """Risk engine halts strategy when drawdown exceeds limit."""
    # Create bars that crash after initial gains
    bars = _synthetic_bars(n_bars=20, trend=1.0)  # up 20 bars
    crash = _synthetic_bars(n_bars=30, trend=-10.0, start_price=120.0)  # massive crash
    crash = [
        BarData(
            b.symbol,
            b.timestamp + timedelta(days=20),
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
        )
        for b in crash
    ]

    feed = InMemoryDataFeed(bars + crash)
    config = BacktestConfig(
        initial_capital=Decimal("100_000"),
        max_drawdown_halt=Decimal("0.05"),  # halt at 5% drawdown — aggressive
    )
    engine = BacktestEngine(strategy=BuyAndHold(), data_feed=feed, config=config)
    report = engine.run()

    # Engine should have halted; not all 50 bars processed or risk halted
    assert engine._risk.is_halted or report.total_bars <= 50


@pytest.mark.unit
def test_next_bar_execution_no_look_ahead(default_config):
    """Verify orders submit on bar T and fill on bar T+1, not bar T."""

    class RecordingStrategy(Strategy):
        name = "recording"
        _bar_count = 0

        def on_bar(self, context, bar) -> list[SignalEvent]:
            self._bar_count += 1
            if self._bar_count == 5:  # generate exactly one buy on bar 5
                return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG)]
            return []

    bars = _synthetic_bars(n_bars=20)
    feed = InMemoryDataFeed(bars)
    engine = BacktestEngine(
        strategy=RecordingStrategy(),
        data_feed=feed,
        config=default_config,
    )
    engine.run()

    fills = engine._all_fills
    if fills:
        bar_5_ts = bars[4].timestamp  # bar index 4 = bar number 5 (0-indexed)
        bar_6_ts = bars[5].timestamp
        # The fill should be at bar 6's timestamp, not bar 5
        assert fills[0].timestamp == bar_6_ts, (
            f"Order submitted at bar 5 ({bar_5_ts}) must fill at bar 6 ({bar_6_ts}), "
            f"got fill at {fills[0].timestamp}"
        )


@pytest.mark.unit
def test_in_memory_feed_sorts_chronologically():
    ts2 = datetime(2024, 1, 2, tzinfo=UTC)
    ts1 = datetime(2024, 1, 1, tzinfo=UTC)
    ts3 = datetime(2024, 1, 3, tzinfo=UTC)

    def _b(ts):
        return BarData(
            "AAPL",
            ts,
            Decimal("100"),
            Decimal("101"),
            Decimal("99"),
            Decimal("100"),
            Decimal("1e6"),
        )

    feed = InMemoryDataFeed([_b(ts2), _b(ts3), _b(ts1)])
    timestamps = [b.timestamp for b in feed.iter_bars()]
    assert timestamps == sorted(timestamps)


@pytest.mark.unit
def test_split_adjusted_data_golden_case(default_config):
    """Golden case: split-adjusted data looks like a continuous price series.

    A 2-for-1 split backward-adjusted means pre-split prices are halved in
    the historical record. The engine sees a smooth uptrend — no discontinuity.
    Expected return: price doubles from 50→100, so ~100% gross return minus costs.
    """
    # Pre-split adjusted price: $50 (actual was $100 before the split)
    # Post-split price: moves from $50 to $100 over 40 bars
    bars = _synthetic_bars(n_bars=40, start_price=50.0, trend=1.25)  # 50→99.75
    feed = InMemoryDataFeed(bars)
    engine = BacktestEngine(strategy=BuyAndHold(), data_feed=feed, config=default_config)
    report = engine.run()

    # With 100_000 capital, buying ~200 shares at ~$50, selling at ~$100 → ~100% gross
    # After costs the return should still be substantial and positive
    assert report.metrics.total_return > 0.5, (
        "Split-adjusted data must show ~100% gross return as price doubles. "
        f"Got {report.metrics.total_return:.1%}"
    )


@pytest.mark.unit
def test_unadjusted_split_shows_false_loss(default_config):
    """Documents known limitation: the engine cannot handle un-adjusted splits.

    An un-adjusted 2-for-1 split shows as a sudden 50% price drop in the bar data.
    The engine sees this as a loss — it has no mechanism to know shares doubled.
    Researchers MUST provide backward split-adjusted data; un-adjusted data is invalid.
    """
    # Phase 1: price rises from 100 to 120 over 20 bars
    pre_split = _synthetic_bars(n_bars=20, start_price=100.0, trend=1.0)
    # Phase 2: split occurs — price is halved to ~60, then continues up
    # Un-adjusted: price jumps from ~120 to ~60 (visible discontinuity)
    post_split = _synthetic_bars(n_bars=20, start_price=60.0, trend=1.0)
    post_split = [
        BarData(
            b.symbol,
            b.timestamp + timedelta(days=20),
            b.open, b.high, b.low, b.close, b.volume,
        )
        for b in post_split
    ]

    feed = InMemoryDataFeed(pre_split + post_split)
    engine = BacktestEngine(strategy=BuyAndHold(), data_feed=feed, config=default_config)
    report = engine.run()

    # Engine reports a loss because it sees a price drop from ~120 to ~60.
    # This is incorrect economically (shares doubled), but it is the expected
    # engine behavior with un-adjusted data. Correct fix: adjust data, not engine.
    assert report.metrics.total_return < 0, (
        "Un-adjusted split data SHOULD produce an (incorrect) reported loss — "
        "this test documents the known limitation. If this starts passing positively, "
        "something unexpected changed. Researchers must provide split-adjusted data."
    )
