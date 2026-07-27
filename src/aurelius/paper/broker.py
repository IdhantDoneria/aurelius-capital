"""Broker abstraction — the paper-trading fill engine.

A Broker takes order requests and, against live ticks, produces fills, positions
and an account balance. PaperBroker simulates this locally so the exact same
strategy/risk/execution stack that ran in the backtest can run continuously on
live data with zero code change — only the Broker implementation swaps for a real
one later (Alpaca, IBKR, ...). That is the point of the abstraction.

Fill model (paper):
  market order : fills immediately at the last tick price -/+ slippage_bps.
  limit  order : rests until a tick crosses it (buy: tick<=limit, sell: tick>=limit),
                 then fills at the limit price (conservative, no price improvement).
  commission   : notional * commission_rate, charged on every fill.

Balance:
  cash          : settled cash.
  equity        : cash + sum(position market value).
  buying_power  : cash (cash account, no margin — ponytail: add margin when a
                  real broker with margin is wired in).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from aurelius.backtesting.events.types import FillEvent, OrderType, Side
from aurelius.backtesting.portfolio.state import PortfolioState
from aurelius.core.logging import get_logger
from aurelius.risk import OrderContext, RiskDecision, RiskEngine

logger = get_logger(__name__)


@dataclass(frozen=True)
class Tick:
    timestamp: datetime
    symbol: str
    price: Decimal


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    strategy_id: str = ""


@dataclass
class OrderResult:
    accepted: bool
    reason: str = ""
    fill: FillEvent | None = None          # set when it filled immediately (market)
    resting: bool = False                  # True when a limit order is working
    order_id: str = ""


@dataclass
class _Resting:
    request: OrderRequest
    order_id: str


class PaperBroker:
    def __init__(
        self,
        cash: Decimal = Decimal("100000"),
        commission_rate: Decimal = Decimal("0.0005"),
        slippage_bps: Decimal = Decimal("2"),
        risk_engine: RiskEngine | None = None,
        on_fill: Callable[[FillEvent], None] | None = None,
    ) -> None:
        self.state = PortfolioState(cash)
        self._commission = commission_rate
        self._slip = slippage_bps
        self._risk = risk_engine
        self._on_fill = on_fill
        self._last: dict[str, Decimal] = {}
        self._resting: list[_Resting] = []
        self._seq = 0

    # ── market data ─────────────────────────────────────────────────────────

    def on_tick(self, tick: Tick) -> list[FillEvent]:
        """Update the mark, then fill any resting limit orders the tick crosses."""
        self._last[tick.symbol] = tick.price
        self.state.position(tick.symbol).last_price = tick.price
        self.state.update_peak()

        fills: list[FillEvent] = []
        still: list[_Resting] = []
        for r in self._resting:
            if r.request.symbol != tick.symbol:
                still.append(r)
                continue
            if self._crosses(r.request, tick.price):
                fills.append(self._fill(
                    r.request, r.request.limit_price, tick.timestamp, r.order_id))
            else:
                still.append(r)
        self._resting = still
        return fills

    @staticmethod
    def _crosses(req: OrderRequest, price: Decimal) -> bool:
        lp = req.limit_price
        if lp is None:
            return False
        return price <= lp if req.side == Side.BUY else price >= lp

    # ── order entry ───────────────────────────────────────────────────────────

    def submit(self, req: OrderRequest, now: datetime | None = None) -> OrderResult:
        now = now or datetime.now(tz=self._tz())
        oid = self._next_id()
        mark = self._last.get(req.symbol)
        if mark is None or mark <= 0:
            return OrderResult(False, "no market data for symbol yet", order_id=oid)

        # Risk screen (Phase 7): reject or clamp before anything hits the book.
        if self._risk is not None:
            ctx = OrderContext(req.symbol, mark, req.quantity, is_buy=req.side == Side.BUY)
            verdict = self._risk.evaluate(ctx, self.state)
            if verdict.decision is RiskDecision.REJECT:
                logger.warning("order_rejected", symbol=req.symbol, reason=verdict.reasons)
                return OrderResult(False, "; ".join(verdict.reasons), order_id=oid)
            if verdict.modified_quantity is not None:
                req = OrderRequest(req.symbol, req.side, verdict.modified_quantity,
                                   req.order_type, req.limit_price, req.strategy_id)

        # Balance check for buys (cash account).
        if req.side == Side.BUY and req.quantity * mark > self.state.cash:
            return OrderResult(False, "insufficient buying power", order_id=oid)

        if req.order_type == OrderType.LIMIT:
            self._resting.append(_Resting(req, oid))
            return OrderResult(True, resting=True, order_id=oid)

        fill = self._fill(req, mark, now, oid)
        return OrderResult(True, fill=fill, order_id=oid)

    # ── fills / accounting ──────────────────────────────────────────────────

    def _fill(self, req: OrderRequest, ref_price: Decimal, now: datetime, oid: str) -> FillEvent:
        slip = ref_price * self._slip / Decimal("10000")
        px = ref_price + slip if req.side == Side.BUY else ref_price - slip  # slippage hurts
        commission = px * req.quantity * self._commission
        fill = FillEvent(
            timestamp=now, symbol=req.symbol, side=req.side, quantity=req.quantity,
            fill_price=px, commission=commission, slippage_cost=slip * req.quantity, order_id=oid,
        )
        pos = self.state.position(req.symbol)
        if req.side == Side.BUY:
            pos.apply_buy(req.quantity, px)
        else:
            pos.apply_sell(req.quantity, px)
        pos.last_price = px
        self.state.debit(-fill.signed_cash_delta())   # signed_cash_delta negative for buys
        logger.info("fill", symbol=req.symbol, side=req.side.value,
                    qty=float(req.quantity), price=float(px))
        if self._on_fill:
            self._on_fill(fill)
        return fill

    # ── account ────────────────────────────────────────────────────────────

    def account(self) -> dict:
        return {
            "cash": self.state.cash,
            "equity": self.state.total_value,
            "buying_power": self.state.cash,
            "unrealized_pnl": self.state.unrealized_pnl,
            "realized_pnl": self.state.realized_pnl,
            "positions": {s: p.quantity for s, p in self.state.open_positions.items()},
            "open_orders": len(self._resting),
        }

    @property
    def open_orders(self) -> int:
        return len(self._resting)

    def _next_id(self) -> str:
        self._seq += 1
        return f"paper-{self._seq}"

    @staticmethod
    def _tz():
        from datetime import UTC
        return UTC
