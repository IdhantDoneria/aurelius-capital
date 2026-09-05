"""Execution model (AIDP M11).

Dependency-injected: the engine depends on the ExecutionModel ABC, never a concrete
one. `CostExecutionModel` fills at the mark price and books the M10 transaction
cost (commission + spread + slippage + √-law impact). Latency, partial fills, and
intraday (VWAP/TWAP/POV) are documented extension points — the interface already
carries `adv` and returns a `Fill` that a partial-fill model would subdivide.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mentisrex.research.simulation.models import Fill, Order


class ExecutionModel(ABC):
    name = "execution"

    @abstractmethod
    def execute(self, order: Order, price: float, adv: float | None = None) -> Fill: ...


class CostExecutionModel(ExecutionModel):
    """Full fill at `price`, cost from an injected M10 TransactionCostModel."""

    name = "cost_model"

    def __init__(self, cost_model) -> None:
        self._cm = cost_model

    def execute(self, order, price, adv=None):
        notional = order.quantity * price
        cost = self._cm.estimate([abs(notional)], adv=[adv] if adv is not None else None)[
            "total_cost"
        ]
        return Fill(
            security_id=order.security_id,
            quantity=order.quantity,
            price=float(price),
            cost=float(cost),
            notional=float(notional),
        )


class FrictionlessExecutionModel(ExecutionModel):
    """Zero-cost full fill — baseline / accounting tests."""

    name = "frictionless"

    def execute(self, order, price, adv=None):
        notional = order.quantity * price
        return Fill(order.security_id, order.quantity, float(price), 0.0, float(notional))
