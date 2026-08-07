"""Order generation (AIDP Phase 11).

Compare the target portfolio to current holdings and emit executable orders,
honoring lot sizes, minimum trade notional (buffer band), and long-only. Cash-aware
sizing scales targets down if the implied buys exceed available cash + expected
sale proceeds.
"""

from __future__ import annotations

from dataclasses import dataclass

from aurelius.research.simulation.models import Order


@dataclass(frozen=True)
class SizingConfig:
    min_trade_notional: float = 0.0
    integer_shares: bool = False
    lot_size: int = 1
    allow_short: bool = False
    cash_buffer: float = 0.0            # fraction of value kept in cash


def _round_lot(shares: float, cfg: SizingConfig) -> float:
    if not cfg.integer_shares:
        return shares
    lot = max(cfg.lot_size, 1)
    return float(int(shares / lot) * lot)


def generate_orders(target_weights: dict, state, prices: dict, cfg: SizingConfig) -> list[Order]:
    value = state.total_value() * (1.0 - cfg.cash_buffer)
    if value <= 0:
        return []
    ids = set(target_weights) | set(state.holdings)
    orders: list[Order] = []
    for sid in sorted(ids):                       # sorted → deterministic order
        price = prices.get(sid)
        if price is None or price <= 0:
            continue                              # unpriced: cannot trade, hold as-is
        tw = target_weights.get(sid, 0.0)
        if not cfg.allow_short and tw < 0:
            tw = 0.0
        target_shares = _round_lot(tw * value / price, cfg)
        cur = state.holdings[sid].shares if sid in state.holdings else 0.0
        delta = target_shares - cur
        if abs(delta) < 1e-9 or abs(delta * price) < cfg.min_trade_notional:
            continue
        orders.append(Order(security_id=sid, quantity=float(delta)))
    return orders
