"""Broker abstraction (AIDP M12).

Dependency-injected: the paper-trading session depends on the `Broker` ABC, never
a concrete class. Two offline, deterministic implementations ship:

* `MockBroker`     — perfect broker: full immediate fills at the marked price,
                     its own book kept with the *reused* M11 accounting core.
* `SimulatedBroker`— deliberately imperfect: seeded partial fills, rejections and
                     slippage, so reconciliation and drift have real divergence to
                     detect. Frictions are the only thing added over MockBroker.

No credentials, no network. Real-broker adapters (IB / Alpaca / Zerodha / FIX)
are interface-only stubs in `adapter.py`.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from aurelius.research.paper_trading.models import (
    BrokerAccount,
    BrokerFill,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    OrderStatus,
)
from aurelius.research.simulation.execution import ExecutionModel, FrictionlessExecutionModel
from aurelius.research.simulation.models import Order
from aurelius.research.simulation.state import PortfolioState


class Broker(ABC):
    name = "broker"

    @abstractmethod
    def set_prices(self, prices: dict) -> None:
        """Publish the marks the broker fills against this tick."""

    @abstractmethod
    def place_order(self, req: OrderRequest, *, adv: float | None = None) -> BrokerOrder: ...

    @abstractmethod
    def poll_fills(self) -> list:
        """Fills produced since the last poll (drains the queue)."""

    @abstractmethod
    def get_account(self) -> BrokerAccount: ...

    def cancel_order(self, broker_order_id: str) -> bool:      # default: nothing open
        return False


class MockBroker(Broker):
    """Perfect fills. The broker's own book reuses the M11 PortfolioState so its
    reported account is produced by the same certified accounting the internal
    book uses — a genuine independent copy, not a mirror of internal state."""

    name = "mock"

    def __init__(self, *, initial_cash: float, account_id: str = "PAPER",
                 execution_model: ExecutionModel | None = None) -> None:
        self._book = PortfolioState(initial_cash)
        self._exec = execution_model or FrictionlessExecutionModel()
        self._account_id = account_id
        self._prices: dict = {}
        self._fill_queue: list = []
        self._seq = 0

    def set_prices(self, prices):
        self._prices = {k: float(v) for k, v in prices.items() if v is not None and v > 0}
        self._book.mark(self._prices)

    def _make_fill(self, order_id, sid, qty, price, cost, when=None) -> BrokerFill:
        fid = hashlib.blake2b(f"{order_id}:{sid}:{self._seq}".encode(), digest_size=8).hexdigest()
        return BrokerFill(fill_id=fid, broker_order_id=order_id, security_id=sid,
                          quantity=float(qty), price=float(price), cost=float(cost), when=when)

    def place_order(self, req, *, adv=None):
        self._seq += 1
        oid = f"{self.name}-{self._seq:06d}"
        price = self._prices.get(req.security_id)
        if price is None:                       # cannot fill an unpriced name → reject
            return BrokerOrder(oid, req.client_order_id, req.security_id, req.quantity,
                               OrderStatus.REJECTED, submitted_at=datetime.now(UTC))
        filled_qty, fill_price = self._fill_terms(req, price)
        cost = self._exec.execute(Order(req.security_id, filled_qty), fill_price, adv).cost \
            if filled_qty else 0.0
        if filled_qty:
            self._book.apply_fill(req.security_id, filled_qty, fill_price, cost)
            self._fill_queue.append(self._make_fill(oid, req.security_id, filled_qty, fill_price, cost))
        status = (OrderStatus.FILLED if abs(filled_qty - req.quantity) < 1e-9
                  else OrderStatus.PARTIALLY_FILLED if filled_qty else OrderStatus.REJECTED)
        return BrokerOrder(oid, req.client_order_id, req.security_id, req.quantity, status,
                           filled_quantity=filled_qty, avg_fill_price=fill_price if filled_qty else 0.0,
                           submitted_at=datetime.now(UTC))

    def _fill_terms(self, req, price):          # perfect broker: full fill at mark
        return req.quantity, price

    def poll_fills(self):
        fills, self._fill_queue = self._fill_queue, []
        return fills

    def get_account(self):
        pos = {sid: BrokerPosition(sid, h.shares, h.cost_basis, h.price)
               for sid, h in self._book.holdings.items()}
        return BrokerAccount(self._account_id, self._book.cash, pos)


class SimulatedBroker(MockBroker):
    """MockBroker + deterministic frictions that create divergence to reconcile:
    `fill_ratio` (<1 → partial fill), `slippage_bps` (price moves against you),
    `reject_every` (Nth order rejected). Fully seeded — no RNG, reproducible."""

    name = "simulated"

    def __init__(self, *, initial_cash: float, fill_ratio: float = 1.0,
                 slippage_bps: float = 0.0, reject_every: int = 0, **kw) -> None:
        super().__init__(initial_cash=initial_cash, **kw)
        self.fill_ratio = fill_ratio
        self.slippage_bps = slippage_bps
        self.reject_every = reject_every

    def _fill_terms(self, req, price):
        if self.reject_every and (self._seq % self.reject_every == 0):
            return 0.0, price
        qty = req.quantity * self.fill_ratio
        slip = self.slippage_bps / 1e4
        # slippage always costs: buys fill higher, sells fill lower
        fill_price = price * (1 + slip) if req.quantity > 0 else price * (1 - slip)
        return qty, fill_price
