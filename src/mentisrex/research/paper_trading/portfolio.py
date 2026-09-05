"""PaperPortfolio (AIDP M12) — the session's internal book.

Thin wrapper over the reused M11 `PortfolioState` (all accounting is M11's, not
re-implemented here) that additionally remembers the last target weights and
ingests broker fills with duplicate protection. This is the "internal" side that
reconciliation compares against the broker's "external" `BrokerAccount`.
"""

from __future__ import annotations

from mentisrex.research.paper_trading.models import AccountSnapshot, BrokerFill, PositionSnapshot
from mentisrex.research.simulation.state import PortfolioState


class PaperPortfolio:
    def __init__(self, initial_capital: float) -> None:
        self.state = PortfolioState(initial_capital)
        self.target: dict = {}
        self._applied_fill_ids: set[str] = set()

    # ── mutation ─────────────────────────────────────────────────────────────
    def set_target(self, weights: dict) -> None:
        self.target = dict(weights or {})

    def mark(self, prices: dict) -> None:
        self.state.mark(prices)

    def ingest_fill(self, fill: BrokerFill) -> bool:
        """Apply a broker fill to the internal book. Idempotent: a fill_id already
        seen is skipped and returns False (duplicate-fill protection)."""
        if fill.fill_id in self._applied_fill_ids:
            return False
        self._applied_fill_ids.add(fill.fill_id)
        self.state.apply_fill(
            fill.security_id, fill.quantity, fill.price, fill.cost, when=fill.when
        )
        return True

    # ── views ────────────────────────────────────────────────────────────────
    @property
    def cash(self) -> float:
        return self.state.cash

    def value(self) -> float:
        return self.state.total_value()

    def weights(self) -> dict:
        return self.state.weights()

    def snapshot(self, external, when=None) -> AccountSnapshot:
        """Paired internal/external account snapshot (external = BrokerAccount)."""
        ext_pos = external.positions if external else {}
        sids = set(self.state.holdings) | set(ext_pos)
        rows = []
        for sid in sorted(sids):
            h = self.state.holdings.get(sid)
            e = ext_pos.get(sid)
            rows.append(
                PositionSnapshot(
                    security_id=sid,
                    internal_qty=h.shares if h else 0.0,
                    external_qty=e.quantity if e else 0.0,
                    internal_price=h.price if h else 0.0,
                    external_price=e.market_price if e else 0.0,
                    internal_cost_basis=h.cost_basis if h else 0.0,
                    external_cost_basis=e.avg_cost if e else 0.0,
                )
            )
        return AccountSnapshot(
            date=when,
            internal_cash=self.cash,
            external_cash=external.cash if external else 0.0,
            internal_value=self.value(),
            external_value=external.total_value() if external else 0.0,
            positions=rows,
        )
