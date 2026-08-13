# Phase 5 Developer Guide: Using the Backtesting Engine

## Quick Start

```python
from mentisrex.backtesting import BacktestEngine, BacktestConfig
from mentisrex.backtesting.data.feed import InMemoryDataFeed
from mentisrex.backtesting.strategy.base import Strategy, StrategyContext
from mentisrex.backtesting.events.types import Direction, MarketEvent, SignalEvent

class MyStrategy(Strategy):
    name = "my_strategy"
    
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        # Get historical closes
        closes = context.close_series(bar.symbol, lookback=20)
        if len(closes) < 20:
            return []
        
        # Your logic here
        sma = sum(closes[-20:]) / 20
        if bar.close > sma:
            return [SignalEvent(
                timestamp=bar.timestamp,
                symbol=bar.symbol,
                direction=Direction.LONG,
                strength=1.0,
            )]
        return []

# Run backtest
config = BacktestConfig(
    initial_capital=Decimal("1_000_000"),
    commission_rate=Decimal("0.001"),
    spread_bps=Decimal("5"),
)
feed = InMemoryDataFeed(bars)
engine = BacktestEngine(MyStrategy(), feed, config)
report = engine.run()
print(report.summary())
```

---

## Core Concepts

### Execution Model

**Next-bar execution:** Orders placed at bar T fill at bar T+1's open price.

```
Bar T (close 100):
  ├─ Strategy sees bar T data
  ├─ Emits LONG signal
  └─ Order placed (status: PENDING)

Bar T+1 (open 101):
  ├─ Order fills at 101 + costs
  ├─ Position opens
  └─ Strategy sees bar T+1 data
```

**No look-ahead:** Strategy cannot see future prices or know whether its order filled until the next bar.

### Temporal Isolation

StrategyContext enforces a read-only view of the past:

```python
@property
def context.history(symbol: str, lookback: int = None) -> list[MarketEvent]:
    """Returns bars with timestamp ≤ current bar's timestamp.
    Never includes the current bar itself."""
```

### Event Processing Order (Per Bar)

1. **FillEvent (priority=1):** Prior bar's pending orders fill at this bar's open
2. **MarketEvent (priority=2):** Current bar data published; strategy.on_bar() called
3. **SignalEvent (priority=3):** Strategy output routed to PortfolioManager for sizing
4. **OrderEvent (priority=4):** Sized order sent to RiskEngine, then pending_orders

This ordering prevents the strategy from seeing its own fills retroactively.

---

## Strategy Interface

### Minimal Implementation

```python
from mentisrex.backtesting.strategy.base import Strategy

class MinimalStrategy(Strategy):
    name = "minimal"
    
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        """Called once per bar for this symbol.
        
        Args:
            context: Read-only view of portfolio state, history, and time
            bar: Current OHLCV bar
        
        Returns:
            List of signals (usually 0-1 per symbol per bar)
        """
        return []  # No action
    
    @property
    def parameters(self) -> dict:
        """Return hyperparameters for reporting."""
        return {}
```

### Lifecycle Hooks

```python
class FullStrategy(Strategy):
    def on_start(self, context: StrategyContext) -> None:
        """Called once before first bar. Use for initialization."""
        # Pre-compute static data, load model, initialize state
        pass
    
    def on_end(self, context: StrategyContext) -> None:
        """Called once after last bar. Use for cleanup."""
        # Close all positions, log final stats
        pass
    
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        """Called for each bar."""
        pass
```

### StrategyContext API

```python
class StrategyContext:
    def history(self, symbol: str, lookback: int = None) -> list[MarketEvent]:
        """Get historical bars for symbol (up to current bar).
        
        Args:
            symbol: e.g., "AAPL"
            lookback: max N most recent bars (or None for all)
        
        Returns:
            List of MarketEvent, sorted by timestamp, oldest first
        """
    
    def close_series(self, symbol: str, lookback: int = None) -> list[Decimal]:
        """Convenience: just close prices (equivalent to [b.close for b in history(...)])"""
    
    @property
    def portfolio(self) -> PortfolioState:
        """Read-only access to current portfolio state.
        
        Use to check:
        - portfolio.position(symbol).quantity (current shares)
        - portfolio.position(symbol).avg_cost (entry price)
        - portfolio.position(symbol).unrealized_pnl
        - portfolio.cash (available cash)
        - portfolio.total_value (NAV)
        - portfolio.gross_leverage (sum of abs exposures)
        - portfolio.drawdown (current drawdown from peak)
        """
    
    @property
    def now(self) -> datetime:
        """Current simulation timestamp (same as bar.timestamp)."""
```

---

## Signal Types

### Direction Enum

```python
class Direction(StrEnum):
    LONG = "long"      # Open/increase long position
    SHORT = "short"    # Open/increase short position
    FLAT = "flat"      # Close all positions in this symbol
```

### SignalEvent

```python
SignalEvent(
    timestamp=bar.timestamp,          # When this signal was generated
    symbol=bar.symbol,                # Which symbol to trade
    direction=Direction.LONG,         # LONG, SHORT, or FLAT
    strength=1.0,                     # 0.0–1.0: fraction of max allocation
    strategy_id="",                   # For multi-strategy setups (optional)
)
```

**Strength:** Controls position size via `config.max_position_pct`:
- `strength=1.0` → allocate `max_position_pct` of NAV
- `strength=0.5` → allocate `0.5 × max_position_pct` of NAV

**FLAT signal:** Closes all positions in that symbol (quantity doesn't matter).

---

## Position Tracking

### Accessing Current Position

```python
pos = context.portfolio.position("AAPL")

# Position state
pos.quantity           # Shares held (+ long, - short)
pos.avg_cost          # Weighted average entry price
pos.last_price        # Current mark-to-market price
pos.realized_pnl      # Locked P&L from closed trades
pos.unrealized_pnl    # Mark-to-market P&L

# Status checks
pos.is_long           # quantity > 0
pos.is_short          # quantity < 0
pos.is_flat           # quantity == 0
pos.market_value      # quantity × last_price
```

### Portfolio Aggregates

```python
context.portfolio.cash              # Cash available
context.portfolio.total_value       # NAV = cash + sum(market_values)
context.portfolio.total_pnl         # Realized + unrealized
context.portfolio.gross_exposure    # Sum of abs(market_values)
context.portfolio.gross_leverage    # gross_exposure / total_value
context.portfolio.net_exposure      # Sum of market_values (signed)
context.portfolio.net_leverage      # net_exposure / total_value
context.portfolio.drawdown          # (current - peak) / peak (e.g., -0.15)
context.portfolio.open_positions    # Dict of non-zero positions
```

---

## Position Sizing & Order Generation

### How Signals Become Orders

1. **You emit:** `SignalEvent(symbol="AAPL", direction=LONG, strength=1.0)`
2. **Engine computes:** Target value = `portfolio.total_value × max_position_pct × strength`
3. **Engine sizes:** Target shares = `floor(target_value / last_price)`
4. **Engine creates:** `OrderEvent(symbol, side=BUY, quantity=delta_shares)`
5. **Engine validates:** RiskEngine checks position size, leverage, drawdown
6. **Result:** Order fills at T+1 open (if not rejected)

### Example: Equal-Weight Pairs

```python
def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
    if bar.symbol == "AAPL":
        return [SignalEvent(
            timestamp=bar.timestamp,
            symbol="AAPL",
            direction=Direction.LONG,
            strength=1.0,  # Go long AAPL at max position size
        )]
    elif bar.symbol == "MSFT":
        return [SignalEvent(
            timestamp=bar.timestamp,
            symbol="MSFT",
            direction=Direction.SHORT,
            strength=1.0,  # Go short MSFT at max position size
        )]
    return []
```

If `max_position_pct=0.10` and `total_value=$1M`:
- AAPL target value = $100k → buy as many shares as possible at `last_price`
- MSFT target value = $100k → short as many shares as possible at `last_price`

---

## Config Reference

```python
from mentisrex.backtesting import BacktestConfig
from decimal import Decimal

config = BacktestConfig(
    # Capital
    initial_capital=Decimal("1_000_000"),
    
    # Date range (None = use full feed range)
    start_date=None,
    end_date=None,
    
    # Costs
    commission_rate=Decimal("0.0010"),        # 10 bps per side
    spread_bps=Decimal("5"),                   # 5 bps half-spread (10 round-trip)
    slippage_impact_bps=Decimal("10"),        # Market impact @ 100% ADV
    max_fill_pct_adv=Decimal("0.20"),         # Fill ≤ 20% ADV per bar
    
    # Constraints
    max_position_pct=Decimal("0.10"),         # Max 10% NAV in one name
    max_gross_leverage=Decimal("1.5"),        # Max 150% gross exposure
    max_drawdown_halt=Decimal("0.20"),        # Halt at 20% drawdown from peak
    
    # Analytics
    risk_free_rate=0.05,                      # Annual for Sharpe/Sortino
    trading_days_per_year=252,
    
    # Reproducibility
    random_seed=42,
    
    # Memory
    max_history_bars=500,                     # Max bars per symbol in context.history
)
```

### Cost Model Defaults (Realistic for US Equities 2024)

| Component | Default | Reasoning |
|-----------|---------|-----------|
| Commission | 10 bps | Institutional broker rate |
| Spread | 5 bps half | Liquid large-cap estimate |
| Slippage | 10 bps @ 100% ADV | Almgren-Chriss calibration |
| Fill % ADV | 20% | Realistic liquidity constraint |

**To simulate different markets:**
- High-frequency: `spread_bps=0.5, slippage_impact_bps=2` (liquid large-cap)
- Small-cap: `spread_bps=20, slippage_impact_bps=50` (illiquid)
- Crypto: `commission_rate=0.0005, spread_bps=10` (lower commissions)

---

## Data Feed

### InMemoryDataFeed (For Research)

```python
from mentisrex.backtesting.data.feed import InMemoryDataFeed, BarData

bars = [
    BarData(
        symbol="AAPL",
        timestamp=datetime(2024, 1, 2, tzinfo=UTC),
        open=Decimal("150.00"),
        high=Decimal("151.50"),
        low=Decimal("149.50"),
        close=Decimal("150.75"),
        volume=Decimal("50_000_000"),  # 50M shares traded
        frequency="1d",                 # Optional
        vwap=Decimal("150.50"),        # Optional
    ),
    # ... more bars
]

feed = InMemoryDataFeed(
    bars,
    start_date=date(2024, 1, 1),   # Optional: filter by date
    end_date=date(2024, 12, 31),
)
```

**Features:**
- Chronologically sorted at construction
- Filters by date range
- All bars loaded in memory (good for <1 year, <100 symbols)

### DuckDBDataFeed (For Production)

```python
from mentisrex.backtesting.data.feed import DuckDBDataFeed

feed = DuckDBDataFeed(
    db_path="market_data.duckdb",
    symbols=["AAPL", "MSFT", "GOOGL"],      # Optional: filter symbols
    frequency="1d",                         # "1d", "1h", "5m", etc.
    start_date=date(2020, 1, 1),           # Optional
    end_date=date(2025, 12, 31),
)
```

**Features:**
- Streams data from disk (low memory footprint)
- Supports multi-year backtests
- Database must exist and contain `(symbol, timestamp, open, high, low, close, volume)` columns

---

## Reports & Metrics

### Equity Curve & Historical Data

```python
report = engine.run()

report.metrics.equity_curve          # List[EquityPoint]
report.metrics.daily_returns         # List[float] of daily returns
report.metrics.drawdown_series       # List[(timestamp, drawdown)]
report.metrics.round_trips           # List[RoundTrip] trades
```

### Performance Metrics

```python
report.metrics.total_return          # e.g., 0.25 = +25%
report.metrics.cagr                  # Annualized return
report.metrics.annualized_volatility # Annualized std dev
report.metrics.sharpe_ratio          # Risk-adjusted return
report.metrics.sortino_ratio         # Downside risk only
report.metrics.max_drawdown          # Worst peak-to-trough (e.g., -0.15)
report.metrics.calmar_ratio          # CAGR / abs(max_drawdown)

# Trading
report.metrics.num_trades            # Total round-trip trades
report.metrics.win_rate              # Fraction of profitable trades
report.metrics.profit_factor         # Gross profit / gross loss
report.metrics.avg_holding_period_days
report.metrics.annual_turnover       # Trades per year
```

### Example: Extract Trade Log

```python
report = engine.run()
for trade in report.metrics.round_trips:
    print(f"{trade.symbol} {trade.side} {trade.quantity} shares")
    print(f"  Entry: {trade.entry_price} @ {trade.entry_time}")
    print(f"  Exit:  {trade.exit_price} @ {trade.exit_time}")
    print(f"  P&L:   ${trade.pnl:,.2f}")
    print(f"  Held:  {trade.holding_days:.1f} days")
```

---

## Common Patterns

### SMA Crossover

```python
class SMACrossover(Strategy):
    name = "sma_crossover"
    
    def __init__(self, fast: int = 10, slow: int = 50):
        self.fast = fast
        self.slow = slow
    
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        closes = context.close_series(bar.symbol, lookback=self.slow + 1)
        if len(closes) < self.slow:
            return []
        
        fast_ma = sum(closes[-self.fast:]) / self.fast
        slow_ma = sum(closes) / self.slow
        pos = context.portfolio.position(bar.symbol)
        
        if fast_ma > slow_ma and pos.is_flat:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG)]
        if fast_ma < slow_ma and pos.is_long:
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        return []
    
    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow}
```

### Mean Reversion

```python
class MeanReversion(Strategy):
    name = "mean_reversion"
    
    def __init__(self, lookback: int = 20, std_devs: float = 2.0):
        self.lookback = lookback
        self.std_devs = std_devs
    
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        closes = context.close_series(bar.symbol, lookback=self.lookback)
        if len(closes) < self.lookback:
            return []
        
        mean = sum(closes) / len(closes)
        variance = sum((c - mean) ** 2 for c in closes) / len(closes)
        std = variance ** 0.5
        
        if bar.close < mean - self.std_devs * std:
            # Price far below mean → buy
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, strength=1.0)]
        if bar.close > mean + self.std_devs * std:
            # Price far above mean → sell/flatten
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        return []
    
    @property
    def parameters(self) -> dict:
        return {"lookback": self.lookback, "std_devs": self.std_devs}
```

### Pairs Trading (Long-Short)

```python
class PairsTrading(Strategy):
    name = "pairs_trading"
    
    def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
        if bar.symbol == "AAPL":
            # Go long AAPL if outperforming
            if self._should_long_aapl(context, bar):
                return [SignalEvent(bar.timestamp, bar.symbol, Direction.LONG, strength=0.5)]
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        
        elif bar.symbol == "MSFT":
            # Go short MSFT if underperforming
            if self._should_short_msft(context, bar):
                return [SignalEvent(bar.timestamp, bar.symbol, Direction.SHORT, strength=0.5)]
            return [SignalEvent(bar.timestamp, bar.symbol, Direction.FLAT)]
        
        return []
    
    def _should_long_aapl(self, context: StrategyContext, bar: MarketEvent) -> bool:
        aapl_closes = context.close_series("AAPL", lookback=20)
        if len(aapl_closes) < 20:
            return False
        return aapl_closes[-1] > sum(aapl_closes) / len(aapl_closes)
    
    def _should_short_msft(self, context: StrategyContext, bar: MarketEvent) -> bool:
        msft_closes = context.close_series("MSFT", lookback=20)
        if len(msft_closes) < 20:
            return False
        return msft_closes[-1] < sum(msft_closes) / len(msft_closes)
```

---

## Debugging & Validation

### Check Position State

```python
def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
    pos = context.portfolio.position(bar.symbol)
    print(f"{bar.symbol}: qty={pos.quantity}, avg_cost={pos.avg_cost}, "
          f"unrealized_pnl={pos.unrealized_pnl}")
```

### Check History Order

```python
def on_bar(self, context: StrategyContext, bar: MarketEvent) -> list[SignalEvent]:
    hist = context.history(bar.symbol, lookback=5)
    for h in hist:
        assert h.timestamp <= bar.timestamp, f"Look-ahead detected! {h.timestamp} > {bar.timestamp}"
```

### Log Signals & Fills

Enable logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check logs for:
- `fill:` entries showing executed fills
- `order_rejected:` showing risk violations
- `backtest_complete:` showing final metrics

---

## Known Limitations & Workarounds

### No Intraday Execution

**Limitation:** All orders fill at bar.open; no mid-bar fills.  
**Workaround:** Run on daily+ bars only (confirmed in tests).

### No Gap Handling

**Limitation:** If price gaps over stop order, it doesn't fill.  
**Workaround:** Use limit orders instead of stop orders for exact fills.

### No Multi-Leg Orders

**Limitation:** Can't place entry + stop-loss as atomic unit.  
**Workaround:** Place as two separate signals (entry first, then stop as protective order).

### Global Halt on Drawdown

**Limitation:** Strategy completely halts at max drawdown; can't trade other symbols.  
**Workaround:** Run strategies on symbol subsets; restart if halted.

### No Model Retraining

**Limitation:** ML models are static (trained once at on_start()).  
**Workaround:** This is validation; train model externally, test backtest as hold-out set.

---

## Performance Tips

### Memory Efficiency

```python
# GOOD: Use DuckDBDataFeed for large backtests
feed = DuckDBDataFeed("market_data.duckdb", symbols=["AAPL"], start_date=date(2000, 1, 1))

# BAD: Loading 20 years × 500 symbols into RAM
bars = [BarData(...) for _ in range(20 * 252 * 500)]  # 2.5M bars
feed = InMemoryDataFeed(bars)
```

### History Limits

```python
# GOOD: Limit history to what you need
closes = context.close_series("AAPL", lookback=50)

# BAD: Requesting all 500 bars unnecessarily
closes = context.close_series("AAPL", lookback=None)
```

### Config Tuning

```python
# For research (small, controlled):
config = BacktestConfig(
    initial_capital=Decimal("100_000"),
    max_history_bars=200,
)

# For production (larger, real):
config = BacktestConfig(
    initial_capital=Decimal("10_000_000"),
    max_history_bars=500,
    commission_rate=Decimal("0.0008"),  # Better rates at scale
)
```

---

## Next Steps

1. **Implement a simple strategy** (SMA crossover or buy-and-hold)
2. **Run on 1 year of data** to verify execution and reporting
3. **Compare results** to known baselines (e.g., buy-and-hold return)
4. **Iterate:** Tweak config, add complexity, measure P&L impact

**For help:** Check `tests/backtesting/` for example strategies and test patterns.
