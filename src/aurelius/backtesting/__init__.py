"""Institutional-grade event-driven backtesting engine.

Entry point:
    from aurelius.backtesting import BacktestEngine, BacktestConfig
    from aurelius.backtesting.data import InMemoryDataFeed
    from aurelius.backtesting.strategy import Strategy

Quick start:
    engine = BacktestEngine(strategy=my_strategy, data_feed=feed, config=config)
    report = engine.run()
    print(report.summary())
"""

from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.engine import BacktestEngine

__all__ = ["BacktestConfig", "BacktestEngine"]
