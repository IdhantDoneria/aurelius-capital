"""Order construction & market-info container (AIDP M14).

Turns portfolio decisions into parent `OrderRequest`s and provides the `MarketInfo`
an algorithm needs to slice them. Order sizing from *weights* is M11's job
(`simulation.orders.generate_orders`) and is reused via `intents_from_target`;
this module only wraps the resulting share deltas into execution requests. Nothing
here re-implements sizing or accounting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurelius.research.execution.ems.models import OrderIntent, OrderRequest, OrderType
from aurelius.research.simulation.models import Order as SimOrder


@dataclass(frozen=True)
class MarketInfo:
    """Per-name market context for scheduling/costing a slice.

    `volume_profile` is a normalized intraday shape (fractions summing to 1) VWAP
    slices against; default is a U-shape. `interval_volume` is expected share volume
    per slice, used by POV. `adv` is average daily $ volume for the M10 impact term.
    """
    prices: dict = field(default_factory=dict)
    adv: dict = field(default_factory=dict)                 # security_id -> $ ADV
    volume_profile: list = field(default_factory=list)      # fractions, len == n_slices
    interval_volume: dict = field(default_factory=dict)     # security_id -> shares/slice

    def price(self, sid: str) -> float | None:
        p = self.prices.get(sid)
        return float(p) if p and p > 0 else None


DEFAULT_VWAP_PROFILE = [0.20, 0.12, 0.10, 0.08, 0.10, 0.12, 0.28]   # U-shape, sums to 1.0


def intents_from_target(target_shares: dict, current_shares: dict | None = None) -> list:
    """Build `OrderIntent`s from a target share book vs the current book. A pure
    diff — no sizing model — for callers that already hold share targets."""
    current = current_shares or {}
    sids = set(target_shares) | set(current)
    out = []
    for sid in sorted(sids):
        delta = float(target_shares.get(sid, 0.0)) - float(current.get(sid, 0.0))
        if abs(delta) > 1e-9:
            out.append(OrderIntent(sid, delta))
    return out


def build_request(intent: OrderIntent, *, order_id: str, market: MarketInfo,
                  order_type: OrderType = OrderType.MARKET, limit_price: float | None = None,
                  algo: str | None = None, urgency: str = "normal") -> OrderRequest:
    """Wrap an intent into an executable parent order, stamping the arrival price."""
    arrival = market.price(intent.security_id) or 0.0
    return OrderRequest(
        order_id=order_id, security_id=intent.security_id, quantity=intent.delta_shares,
        order_type=order_type, limit_price=limit_price, algo=algo,
        arrival_price=arrival, urgency=urgency)


def build_requests(intents, *, market: MarketInfo, id_prefix: str = "ord",
                   order_type: OrderType = OrderType.MARKET, algo: str | None = None) -> list:
    return [build_request(it, order_id=f"{id_prefix}-{i:06d}", market=market,
                          order_type=order_type, algo=algo)
            for i, it in enumerate(intents, start=1)]


# ── order-type factories (deterministic sim-first) ───────────────────────────────

def market_order(order_id, security_id, quantity, *, arrival_price=0.0) -> OrderRequest:
    return OrderRequest(order_id, security_id, quantity, OrderType.MARKET, arrival_price=arrival_price)


def limit_order(order_id, security_id, quantity, limit_price, *, arrival_price=0.0) -> OrderRequest:
    return OrderRequest(order_id, security_id, quantity, OrderType.LIMIT, limit_price=limit_price,
                        arrival_price=arrival_price)


def stop_order(order_id, security_id, quantity, stop_price, *, arrival_price=0.0) -> OrderRequest:
    # stop = interface only; carried as limit_price=stop for the sim broker.
    return OrderRequest(order_id, security_id, quantity, OrderType.STOP, limit_price=stop_price,
                        arrival_price=arrival_price)


def twap_order(order_id, security_id, quantity, *, arrival_price=0.0) -> OrderRequest:
    return OrderRequest(order_id, security_id, quantity, OrderType.TWAP, arrival_price=arrival_price)


def vwap_order(order_id, security_id, quantity, *, arrival_price=0.0) -> OrderRequest:
    return OrderRequest(order_id, security_id, quantity, OrderType.VWAP, arrival_price=arrival_price)


def pov_order(order_id, security_id, quantity, *, arrival_price=0.0) -> OrderRequest:
    return OrderRequest(order_id, security_id, quantity, OrderType.POV, arrival_price=arrival_price)


def to_sim_orders(requests) -> list:
    """Project parent orders to M11 `Order`s for the M12/M13 pre-trade risk gate,
    whose `.check(orders, state, prices)` contract speaks M11 Orders."""
    return [SimOrder(r.security_id, r.quantity) for r in requests]
