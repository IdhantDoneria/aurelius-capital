"""BacktestConfig — all engine parameters in one place.

Single config object passed to BacktestEngine. Every backtest is
fully described by its config + data version → reproducible results.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class BacktestConfig:
    # Capital
    initial_capital: Decimal = Decimal("1_000_000")

    # Date range (None = use full DataFeed range)
    start_date: date | None = None
    end_date: date | None = None

    # Execution cost model
    commission_rate: Decimal = Decimal("0.0010")  # 10 bps per side — institutional rate
    spread_bps: Decimal = Decimal("5")  # 5 bps half-spread; buy pays +5bps, sell pays -5bps
    slippage_impact_bps: Decimal = Decimal("10")  # market impact coefficient (10 bps at 100% ADV)
    max_fill_pct_adv: Decimal = Decimal("0.20")  # fill at most 20% of avg daily volume per bar

    # Portfolio constraints
    max_position_pct: Decimal = Decimal("0.10")  # max 10% of NAV in one name
    max_gross_leverage: Decimal = Decimal("1.5")  # max 150% gross exposure
    max_drawdown_halt: Decimal = Decimal("0.20")  # halt strategy at 20% drawdown from peak

    # Analytics
    risk_free_rate: float = 0.05  # annual, for Sharpe/Sortino calculation
    trading_days_per_year: int = 252

    # Reproducibility
    random_seed: int = 42

    # Memory
    max_history_bars: int = 500  # max bars per symbol kept in StrategyContext
