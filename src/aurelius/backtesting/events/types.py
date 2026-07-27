"""Concrete event types for the backtesting engine.

Each event type carries exactly what it needs — no more.
ClassVar[int] EVENT_TYPE drives EventQueue ordering.

Ordering rationale:
  FILL=1  — fills from T-1's orders execute at T's open; must see portfolio state
             before strategy sees T's bar data.
  MARKET=2 — bar data published; strategy's on_bar() called.
  SIGNAL=3 — strategy output; routed to PortfolioManager for sizing.
  ORDER=4  — sized order; sent to RiskEngine, then pending_orders list.
"""

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import uuid4


def _next_seq() -> int:
    return next(_SEQ)


_SEQ: itertools.count = itertools.count()


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"   # exit all positions in this symbol


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


# ── FILL ─────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class FillEvent:
    """Confirmed execution. Immutable once created."""

    EVENT_TYPE: ClassVar[int] = 1  # processes first within a timestamp

    timestamp: datetime
    symbol: str
    side: Side
    quantity: Decimal
    fill_price: Decimal
    commission: Decimal
    slippage_cost: Decimal   # monetary cost of slippage, already embedded in fill_price
    order_id: str
    _seq: int = field(default_factory=_next_seq, repr=False)

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.fill_price

    @property
    def total_cost(self) -> Decimal:
        """Total cash impact: notional + commission. Slippage is already in fill_price."""
        return self.notional + self.commission

    def signed_cash_delta(self) -> Decimal:
        """Cash change from this fill. Negative for buys (cash out), positive for sells."""
        if self.side == Side.BUY:
            return -(self.notional + self.commission)
        return self.notional - self.commission


# ── MARKET ───────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class MarketEvent:
    """One OHLCV bar. Drives strategy execution."""

    EVENT_TYPE: ClassVar[int] = 2

    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    frequency: str = "1d"
    vwap: Decimal | None = None
    _seq: int = field(default_factory=_next_seq, repr=False)


# ── SIGNAL ───────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class SignalEvent:
    """Strategy output: direction + strength for one symbol.

    strength: 0.0-1.0 multiplier on max_position_pct.
    strategy_id: which strategy generated this (for multi-strategy setups).
    """

    EVENT_TYPE: ClassVar[int] = 3

    timestamp: datetime
    symbol: str
    direction: Direction
    strength: float = 1.0       # 1.0 = full allocation per config.max_position_pct
    strategy_id: str = ""
    _seq: int = field(default_factory=_next_seq, repr=False)


# ── ORDER ────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class OrderEvent:
    """Proposed trade. Subject to risk checks before execution."""

    EVENT_TYPE: ClassVar[int] = 4

    timestamp: datetime
    symbol: str
    order_type: OrderType
    side: Side
    quantity: Decimal
    limit_price: Decimal | None = None   # required for LIMIT orders
    stop_price: Decimal | None = None    # required for STOP orders
    order_id: str = field(default_factory=lambda: str(uuid4()))
    strategy_id: str = ""
    _seq: int = field(default_factory=_next_seq, repr=False)
