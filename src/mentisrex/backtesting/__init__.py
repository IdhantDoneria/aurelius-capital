"""Institutional-grade event-driven backtesting engine.

Entry point:
    from mentisrex.backtesting import BacktestEngine, BacktestConfig
    from mentisrex.backtesting.data import InMemoryDataFeed
    from mentisrex.backtesting.strategy import Strategy

Quick start:
    engine = BacktestEngine(strategy=my_strategy, data_feed=feed, config=config)
    report = engine.run()
    print(report.summary())
"""

from mentisrex.backtesting.config import BacktestConfig
from mentisrex.backtesting.engine import BacktestEngine

__all__ = ["BacktestConfig", "BacktestEngine"]
