"""Execution-algorithm framework (AIDP M14).

The `ExecutionAlgorithm` ABC + a name→class registry. An algorithm's whole job is
to turn one parent `OrderRequest` + `MarketInfo` into an `ExecutionPlan` (a schedule
+ one child `OrderRequest` per slice). It does NOT talk to the broker or the book —
the EMS drives the plan against the broker and tracks progress. This keeps algorithms
pure and deterministic (plan is a function of inputs), so they are trivially testable
and replayable. Concrete algos live in `execution_algorithms.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from mentisrex.research.execution.ems.models import ExecutionPlan, OrderRequest, OrderType


class ExecutionAlgorithm(ABC):
    name = "algo"

    @abstractmethod
    def schedule(self, order: OrderRequest, market) -> object:
        """Return an ExecutionSchedule for `order` given `market` (MarketInfo)."""

    def plan(self, order: OrderRequest, market) -> ExecutionPlan:
        sched = self.schedule(order, market)
        children = [self._child(order, s) for s in sched.slices]
        return ExecutionPlan(order_id=order.order_id, algo=self.name, schedule=sched,
                             child_orders=children)

    def _child(self, order: OrderRequest, sl) -> OrderRequest:
        # child orders execute immediately at the broker (marketable) regardless of the
        # parent algo; the parent algo controls *timing/size*, not the child order type.
        return replace(order, order_id=f"{order.order_id}.{sl.index}", quantity=sl.quantity,
                       order_type=OrderType.MARKET if order.order_type in _ALGO_TYPES else order.order_type,
                       algo=self.name)


_ALGO_TYPES = {OrderType.TWAP, OrderType.VWAP, OrderType.POV}

_REGISTRY: dict = {}


def register(cls):
    """Class decorator: register an algorithm under its `name`."""
    _REGISTRY[cls.name] = cls
    return cls


def get_algorithm(name: str, **kw) -> ExecutionAlgorithm:
    if name not in _REGISTRY:
        raise KeyError(f"unknown execution algorithm {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name](**kw)


def available() -> list:
    return sorted(_REGISTRY)
