"""PaperTradingSession — the live-state loop (AIDP M12).

One tick (`step`) is: mark → generate orders (reused M11 `generate_orders`) →
pre-trade risk gate → send to the injected broker → ingest fills into the internal
book (reused M11 accounting) → reconcile internal vs broker → measure drift →
record. `run` drives a timeline off injected providers, exactly like the M11
simulation engine, but against an external broker instead of a fill model.

Nothing here re-implements accounting, order sizing, cost, or validation — those
are M10/M11/M9 and are injected or imported. This module is the bridge.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from mentisrex.research.paper_trading.drift import DriftThresholds, compute_drift
from mentisrex.research.paper_trading.models import (
    ExecutionRecord,
    OrderRequest,
    OrderStatus,
    SyncEvent,
)
from mentisrex.research.paper_trading.portfolio import PaperPortfolio
from mentisrex.research.paper_trading.reconciliation import ReconciliationConfig, reconcile
from mentisrex.research.paper_trading.risk import PreTradeRiskGate
from mentisrex.research.simulation.models import EquityPoint, Trade
from mentisrex.research.simulation.orders import SizingConfig, generate_orders


@dataclass
class SessionConfig:
    initial_capital: float = 1_000_000.0
    sizing: SizingConfig = field(default_factory=SizingConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)
    drift_thresholds: DriftThresholds = field(default_factory=DriftThresholds)
    expected_interval_days: float = 0.0  # 0 → timing drift disabled
    periods_per_year: int = 252


class PaperTradingSession:
    def __init__(
        self,
        *,
        broker,
        config: SessionConfig | None = None,
        risk_gate: PreTradeRiskGate | None = None,
        cost_model=None,
    ) -> None:
        self.broker = broker
        self.config = config or SessionConfig()
        self.risk_gate = risk_gate or PreTradeRiskGate()
        self._cost_model = cost_model
        self.book = PaperPortfolio(self.config.initial_capital)

        self.sync_events: list[SyncEvent] = []
        self.reconciliations: list = []
        self.drifts: list = []
        self.records: list[ExecutionRecord] = []
        self.equity_curve: list[EquityPoint] = []
        self.trades: list[Trade] = []
        self._broker_fill_ids: list[str] = []
        self._applied_fill_ids: list[str] = []
        self._last_date: date | None = None
        self._seq = 0
        self.total_cost = 0.0

    # ── one tick ──────────────────────────────────────────────────────────────
    def step(self, when: date, target: dict, prices: dict, *, adv_provider=None) -> SyncEvent:
        cfg = self.config
        prices = {k: float(v) for k, v in prices.items() if v is not None and v > 0}
        self.book.set_target(target or {})
        self.book.mark(prices)
        self.broker.set_prices(prices)

        orders = generate_orders(target or {}, self.book.state, prices, cfg.sizing)
        approved, _rejected = self.risk_gate.check(orders, self.book.state, prices)

        expected_cost = self._expected_cost(approved, prices)
        day_cost, slippage_bps_num, slippage_den = 0.0, 0.0, 0.0
        for o in approved:
            self._seq += 1
            coid = f"c-{self._seq:06d}"
            adv = adv_provider(o.security_id, when) if adv_provider else None
            bo = self.broker.place_order(OrderRequest(coid, o.security_id, o.quantity), adv=adv)
            self.records.append(
                ExecutionRecord(
                    coid,
                    bo.broker_order_id,
                    o.security_id,
                    o.quantity,
                    bo.filled_quantity,
                    bo.avg_fill_price,
                    0.0,
                    bo.status,
                    when,
                )
            )

        fills = self.broker.poll_fills()
        for f in fills:
            self._broker_fill_ids.append(f.fill_id)
            if self.book.ingest_fill(f):
                self._applied_fill_ids.append(f.fill_id)
                self.trades.append(
                    Trade(
                        f.security_id, f.quantity, f.price, f.cost, f.quantity * f.price, date=when
                    )
                )
                day_cost += f.cost
                mark = prices.get(f.security_id)
                if mark:
                    slippage_bps_num += abs(f.price - mark) / mark * 1e4 * abs(f.quantity)
                    slippage_den += abs(f.quantity)
        self.total_cost += day_cost
        exec_bps = slippage_bps_num / slippage_den if slippage_den else 0.0

        external = self.broker.get_account()
        pending = [
            (r.client_order_id, self._age(r.when, when))
            for r in self.records
            if r.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
        ]
        rec = reconcile(
            self.book.state,
            external,
            when=when,
            config=cfg.reconciliation,
            pending_orders=pending,
            applied_fill_ids=self._applied_fill_ids,
            broker_fill_ids=self._broker_fill_ids,
        )
        self.reconciliations.append(rec)

        timing_gap = 0.0
        if cfg.expected_interval_days and self._last_date is not None:
            timing_gap = max(0.0, (when - self._last_date).days - cfg.expected_interval_days)
        drift = compute_drift(
            self.book.state,
            external,
            target or {},
            when=when,
            timing_gap_days=timing_gap,
            execution_bps=exec_bps,
            expected_cost=expected_cost,
            actual_cost=day_cost,
            thresholds=cfg.drift_thresholds,
        )
        self.drifts.append(drift)

        v = self.book.value()
        e = self.book.state.exposures()
        self.equity_curve.append(EquityPoint(when, v, self.book.cash, e["gross"], e["net"]))
        self._last_date = when

        ev = SyncEvent(
            seq=len(self.sync_events),
            date=when,
            n_orders=len(approved),
            n_fills=len(fills),
            reconciled=rec.ok,
            n_drift_alerts=len(drift.alerts),
            note="; ".join(drift.alerts) if drift.alerts else ("ok" if rec.ok else "break"),
        )
        self.sync_events.append(ev)
        return ev

    def run(
        self, timeline, target_provider, price_provider, *, adv_provider=None
    ) -> list[SyncEvent]:
        for d in timeline:
            tgt = target_provider(d) or {}
            cand = set(self.book.state.holdings) | set(tgt)
            prices = {sid: price_provider(sid, d) for sid in cand}
            self.step(d, tgt, prices, adv_provider=adv_provider)
        return self.sync_events

    # ── helpers ───────────────────────────────────────────────────────────────
    def _expected_cost(self, orders, prices) -> float | None:
        if self._cost_model is None or not orders:
            return None
        notionals = [abs(o.quantity * prices.get(o.security_id, 0.0)) for o in orders]
        return float(self._cost_model.estimate(notionals)["total_cost"])

    @staticmethod
    def _age(start, now) -> float | None:
        return (now - start).days if start and now else None

    def fingerprint(self) -> str:
        """Deterministic id over the realized sync sequence."""
        body = "|".join(
            f"{s.date}:{s.n_orders}:{s.n_fills}:{int(s.reconciled)}" for s in self.sync_events
        )
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()
