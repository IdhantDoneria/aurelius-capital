"""Event types and the EventQueue.

EventType priority values enforce within-timestamp ordering:
  FILL(1) → MARKET(2) → SIGNAL(3) → ORDER(4)

Fill from T-1's order processes before T's market data,
so the portfolio reflects yesterday's execution when the strategy runs today.
"""

from aurelius.backtesting.events.base import EventQueue
from aurelius.backtesting.events.types import (
    Direction,
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderType,
    Side,
    SignalEvent,
)

__all__ = [
    "Direction",
    "EventQueue",
    "FillEvent",
    "MarketEvent",
    "OrderEvent",
    "OrderType",
    "Side",
    "SignalEvent",
]
