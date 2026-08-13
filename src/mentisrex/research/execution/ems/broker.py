"""Execution broker abstraction (AIDP M14).

Dependency-injected: the EMS depends on the `ExecutionBroker` ABC, never a concrete
class. The two offline implementations wrap the *certified M12 brokers* — the fill
simulation and M11 accounting are M12's, not re-implemented here. M14 adds only the
richer OMS-facing surface (7 methods) M12 doesn't expose: order-status lookup,
cancel of an unfilled remainder, replace, and fill history.

* `MockExecutionBroker`      — wraps M12 `MockBroker` (perfect immediate fills).
* `SimulatedExecutionBroker` — wraps M12 `SimulatedBroker` (partial fills, slippage,
                               rejects) → realistic divergence for reconciliation.

No credentials, no network. Real-broker adapters are interface-only in `adapter.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mentisrex.research.execution.ems.models import BrokerFill, OrderStatus
from mentisrex.research.execution.ems.models import OrderRequest as EmsOrderRequest
from mentisrex.research.paper_trading.broker import MockBroker, SimulatedBroker
from mentisrex.research.paper_trading.models import BrokerOrder
from mentisrex.research.paper_trading.models import OrderRequest as M12OrderRequest


class ExecutionBroker(ABC):
    name = "execution_broker"

    @abstractmethod
    def set_prices(self, prices: dict) -> None: ...

    @abstractmethod
    def submit_order(self, req: EmsOrderRequest, *, adv: float | None = None) -> BrokerOrder: ...

    @abstractmethod
    def get_fills(self) -> list:
        """Drain fills produced since the last call (list[BrokerFill])."""

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> BrokerOrder | None: ...

    @abstractmethod
    def get_positions(self) -> dict: ...

    @abstractmethod
    def get_account(self): ...

    def cancel_order(self, broker_order_id: str) -> bool:
        return False

    def replace_order(self, broker_order_id: str, new_quantity: float) -> bool:
        return False


class _WrappingBroker(ExecutionBroker):
    """Shared wrapper: translates M14 requests to M12, records every acknowledgement
    so status/cancel/replace can be answered. The underlying M12 broker fills at the
    published mark on submit (simulation-first), so an unfilled remainder is a resting
    quantity the OMS may cancel — there is no separate resting book to reconcile."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._orders: dict = {}           # broker_order_id -> BrokerOrder

    def set_prices(self, prices):
        self._inner.set_prices(prices)

    def submit_order(self, req, *, adv=None):
        m12 = M12OrderRequest(
            client_order_id=req.order_id,
            security_id=req.security_id,
            quantity=req.quantity,
            order_type=req.order_type.value if hasattr(req.order_type, "value") else str(req.order_type),
            limit_price=req.limit_price)
        ack = self._inner.place_order(m12, adv=adv)
        self._orders[ack.broker_order_id] = ack
        return ack

    def get_fills(self):
        fills = self._inner.poll_fills()
        return [self._as_ems_fill(f) for f in fills]

    @staticmethod
    def _as_ems_fill(f) -> BrokerFill:
        return f                          # M12 BrokerFill is M14's BrokerFill (re-exported)

    def get_order_status(self, broker_order_id):
        return self._orders.get(broker_order_id)

    def get_positions(self):
        return self.get_account().positions

    def get_account(self):
        return self._inner.get_account()

    def cancel_order(self, broker_order_id):
        """Cancel the unfilled remainder. The M12 broker fills synchronously, so a
        fully-filled order can't be cancelled (returns False); anything else has its
        remainder released and the local ack marked CANCELLED."""
        ack = self._orders.get(broker_order_id)
        if ack is None or ack.status == OrderStatus.FILLED.value or ack.status == "filled":
            return False
        self._orders[broker_order_id] = _with_status(ack, "cancelled")
        return True

    def replace_order(self, broker_order_id, new_quantity):
        ack = self._orders.get(broker_order_id)
        if ack is None:
            return False
        # simulation-first: cancel the old remainder; caller re-submits the new qty
        return self.cancel_order(broker_order_id)


class MockExecutionBroker(_WrappingBroker):
    name = "mock"

    def __init__(self, *, initial_cash: float, account_id: str = "EMS", **kw) -> None:
        super().__init__(MockBroker(initial_cash=initial_cash, account_id=account_id, **kw))


class SimulatedExecutionBroker(_WrappingBroker):
    name = "simulated"

    def __init__(self, *, initial_cash: float, fill_ratio: float = 1.0,
                 slippage_bps: float = 0.0, reject_every: int = 0,
                 account_id: str = "EMS", **kw) -> None:
        super().__init__(SimulatedBroker(
            initial_cash=initial_cash, fill_ratio=fill_ratio, slippage_bps=slippage_bps,
            reject_every=reject_every, account_id=account_id, **kw))


def _with_status(ack: BrokerOrder, status: str) -> BrokerOrder:
    from dataclasses import replace
    return replace(ack, status=status)
