"""Holdings, cash ledger, and portfolio accounting (AIDP M11).

The only mutable state in the engine. Accounting is exact and double-entry-checked:
every fill moves cash by −(qty·price)−cost and updates the position's average cost
and realized P&L with correct long / short / flip handling. `CashLedger` records
every flow so the run can be reconciled (Σ flows + initial == final cash).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from aurelius.research.simulation.models import Holding


@dataclass
class CashLedger:
    initial: float
    cash: float = 0.0
    entries: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.initial

    def post(self, amount: float, kind: str, when: date | None = None,
             security_id: str | None = None) -> None:
        self.cash += amount
        self.entries.append({"date": when.isoformat() if when else None, "kind": kind,
                             "amount": amount, "security_id": security_id})

    def reconciles(self, tol: float = 1e-6) -> bool:
        return abs(self.initial + sum(e["amount"] for e in self.entries) - self.cash) < tol


class PortfolioState:
    def __init__(self, initial_capital: float) -> None:
        self.ledger = CashLedger(initial=initial_capital)
        self.holdings: dict[str, Holding] = {}
        self.realized_pnl_total = 0.0

    @property
    def cash(self) -> float:
        return self.ledger.cash

    # ── fills / accounting ────────────────────────────────────────────────────

    def apply_fill(self, security_id: str, qty: float, price: float, cost: float,
                   when: date | None = None) -> float:
        """Apply an executed fill. Returns realized P&L booked on this fill."""
        # cash: pay for buys, receive for sells, always pay the cost
        self.ledger.post(-(qty * price) - cost, kind="fill", when=when, security_id=security_id)

        h = self.holdings.get(security_id)
        s0 = h.shares if h else 0.0
        cb = h.cost_basis if h else 0.0
        realized_before = h.realized_pnl if h else 0.0
        opened = h.opened_at if h else None

        realized_delta = 0.0
        new = s0 + qty
        if s0 == 0.0 or (s0 > 0 and qty > 0) or (s0 < 0 and qty < 0):
            # opening or increasing → weighted-average cost
            cost_basis = (s0 * cb + qty * price) / new if new != 0 else 0.0
            if s0 == 0.0:
                opened = when
        elif abs(qty) <= abs(s0) + 1e-12:
            # reducing / closing on the same side → realize, keep avg cost
            realized_delta = (price - cb) * (-qty)
            cost_basis = cb if abs(new) > 1e-12 else 0.0
            if abs(new) <= 1e-12:
                opened = None
        else:
            # flip: close the whole position, open the remainder at the fill price
            realized_delta = (price - cb) * s0
            cost_basis = price
            opened = when

        self.realized_pnl_total += realized_delta
        if abs(new) <= 1e-12:
            self.holdings.pop(security_id, None)
        else:
            self.holdings[security_id] = Holding(
                security_id=security_id, shares=new, cost_basis=cost_basis,
                price=price, realized_pnl=realized_before + realized_delta, opened_at=opened)
        return realized_delta

    # ── valuation ─────────────────────────────────────────────────────────────

    def mark(self, prices: dict) -> None:
        for sid, h in list(self.holdings.items()):
            p = prices.get(sid)
            if p is not None and p > 0:
                self.holdings[sid] = Holding(
                    security_id=sid, shares=h.shares, cost_basis=h.cost_basis, price=float(p),
                    realized_pnl=h.realized_pnl, opened_at=h.opened_at)

    def positions_value(self) -> float:
        return sum(h.market_value for h in self.holdings.values())

    def total_value(self) -> float:
        return self.cash + self.positions_value()

    def weights(self) -> dict[str, float]:
        v = self.total_value()
        return {sid: h.market_value / v for sid, h in self.holdings.items()} if v > 0 else {}

    def exposures(self) -> dict:
        v = self.total_value() or 1.0
        longs = sum(h.market_value for h in self.holdings.values() if h.shares > 0)
        shorts = sum(-h.market_value for h in self.holdings.values() if h.shares < 0)
        gross = longs + shorts
        net = longs - shorts
        return {"gross": gross / v, "net": net / v, "long": longs / v,
                "short": shorts / v, "cash_weight": self.cash / v}

    def unrealized_pnl(self) -> float:
        return sum(h.unrealized_pnl for h in self.holdings.values())
