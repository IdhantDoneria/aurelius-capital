"""Order routing (AIDP M14).

`ExecutionRouter` picks the broker and algorithm for each parent order and records
an auditable `RoutingDecision`. The default policy is deliberately simple and
deterministic: honour an explicit per-order algo override, else map order type →
algorithm; pick the named/only broker. Smart order routing, venue selection and
liquidity-aware splitting are documented production extensions — the `RoutingDecision`
record and the broker registry are the seams they plug into.
"""

from __future__ import annotations

from mentisrex.research.execution.ems.models import OrderType, RoutingDecision

_TYPE_TO_ALGO = {
    OrderType.MARKET: "immediate",
    OrderType.LIMIT: "immediate",
    OrderType.STOP: "immediate",
    OrderType.TWAP: "twap",
    OrderType.VWAP: "vwap",
    OrderType.POV: "pov",
}


class ExecutionRouter:
    def __init__(
        self, brokers: dict, *, default_broker: str | None = None, default_algo: str = "immediate"
    ) -> None:
        if not brokers:
            raise ValueError("router needs at least one broker")
        self.brokers = brokers
        self.default_broker = default_broker or next(iter(brokers))
        self.default_algo = default_algo

    def route(self, order, *, constraints: dict | None = None) -> RoutingDecision:
        constraints = constraints or {}
        broker = constraints.get("broker", self.default_broker)
        if broker not in self.brokers:
            broker = self.default_broker
        if order.algo:
            algo, reason = order.algo, "order_override"
        else:
            algo = _TYPE_TO_ALGO.get(order.order_type, self.default_algo)
            reason = f"order_type:{order.order_type.value}"
        # high-urgency parents collapse to immediate regardless of type
        if order.urgency == "high" and algo != "immediate":
            algo, reason = "immediate", "urgency:high"
        return RoutingDecision(
            order_id=order.order_id,
            broker=broker,
            algo=algo,
            reason=reason,
            constraints=dict(constraints),
        )

    def broker_for(self, decision: RoutingDecision):
        return self.brokers[decision.broker]
