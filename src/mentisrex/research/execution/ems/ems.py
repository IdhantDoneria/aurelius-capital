"""Execution Management System (AIDP M14).

The orchestrator. Drives the full pre-trade → execution → post-trade pipeline for a
batch of parent orders:

    parent orders
      → M13 risk gate         (reject blocks execution — never routed)
      → OMS approve           (lifecycle + audit trail)
      → router                (broker + algorithm, recorded)
      → algorithm.plan        (child orders + schedule)
      → broker.submit_order   (M12 fill engine + M11 accounting)
      → FillProcessor         (dedupe → OMS fills → M12 book)
      → ExecutionReport

Nothing here re-implements risk, accounting, cost or fills — each is injected or
imported from M10/M11/M12/M13. The EMS is the wiring, deterministic and replayable.
"""

from __future__ import annotations

from dataclasses import dataclass

# populate the algorithm registry (import for side effect)
from mentisrex.research.execution.ems import execution_algorithms  # noqa: F401
from mentisrex.research.execution.ems.algorithms import get_algorithm
from mentisrex.research.execution.ems.fills import FillProcessor
from mentisrex.research.execution.ems.models import OrderStatus
from mentisrex.research.execution.ems.oms import OMS
from mentisrex.research.execution.ems.orders import to_sim_orders
from mentisrex.research.execution.ems.router import ExecutionRouter


@dataclass
class ExecutionConfig:
    twap_slices: int = 5
    pov_participation: float = 0.10
    vwap_profile: list | None = None
    cancel_unfilled_remainder: bool = False


class ExecutionSession:
    """Mutable session record: the OMS (audit trail), routing decisions, fills, and
    per-order reports. Everything surfaced (reports/metrics) is frozen; the session
    itself is the run's accumulator, like the M12 PaperTradingSession."""

    def __init__(
        self, *, config: ExecutionConfig | None = None, book=None, session_id: str = "exec"
    ) -> None:
        self.session_id = session_id
        self.config = config or ExecutionConfig()
        self.oms = OMS()
        self.book = book  # optional M12 PaperPortfolio
        self.fills_processor = FillProcessor()
        self.routing_decisions: list = []
        self.rejections: list = []  # (order_id, security_id, quantity, reason)
        self.plans: list = []

    @property
    def fills(self) -> list:
        return self.fills_processor.processed

    def reports(self) -> list:
        return self.oms.reports()


class EMS:
    def __init__(
        self, router: ExecutionRouter, *, risk_gate=None, config: ExecutionConfig | None = None
    ) -> None:
        self.router = router
        self.risk_gate = risk_gate  # M13 RiskGate / M12 PreTradeRiskGate (.check)
        self.config = config or ExecutionConfig()

    def execute(
        self,
        requests,
        market,
        *,
        book=None,
        adv_provider=None,
        session: ExecutionSession | None = None,
        session_id: str = "exec",
    ) -> ExecutionSession:
        sess = session or ExecutionSession(config=self.config, book=book, session_id=session_id)
        prices = {k: float(v) for k, v in market.prices.items() if v and v > 0}

        # Publish marks to every broker ONCE per batch. set_prices re-marks the whole
        # (growing) book, so calling it per-order would be O(N²) — hoist it here.
        for broker in self.router.brokers.values():
            broker.set_prices(prices)

        approved, blocked = self._risk_screen(requests, prices, sess)
        for req in blocked:
            self._record_reject(sess, req, "risk_gate")

        for req in approved:
            self._execute_one(sess, req, market, adv_provider)
        return sess

    # ── pipeline steps ──────────────────────────────────────────────────────────
    def _risk_screen(self, requests, prices, sess):
        # No gate, or no internal book to project the trade against → cannot screen,
        # allow all (orders still go through validate/approve).
        if self.risk_gate is None or sess.book is None:
            return list(requests), []
        _, rejected = self.risk_gate.check(to_sim_orders(requests), sess.book.state, prices)
        rejected_ids = {o.security_id for o, _ in rejected}
        approved = [r for r in requests if r.security_id not in rejected_ids]
        blocked = [r for r in requests if r.security_id in rejected_ids]
        return approved, blocked

    def _execute_one(self, sess, req, market, adv_provider):
        oms = sess.oms
        oms.create(req)
        oms.validate(req.order_id, ok=abs(req.quantity) > 0 and req.arrival_price >= 0)
        if oms.status(req.order_id) == OrderStatus.REJECTED:
            return
        oms.approve(req.order_id)

        decision = self.router.route(req)
        sess.routing_decisions.append(decision)
        broker = self.router.broker_for(decision)  # prices already published for the batch

        algo = self._make_algo(decision.algo)
        plan = algo.plan(req, market)
        sess.plans.append(plan)

        oms.submit(req.order_id)
        for child in plan.child_orders:
            if abs(child.quantity) < 1e-12:
                continue
            adv = (
                adv_provider(child.security_id)
                if adv_provider
                else market.adv.get(child.security_id)
            )
            broker.submit_order(child, adv=adv)
            for bf in broker.get_fills():
                sess.fills_processor.process(
                    bf, parent_id=req.order_id, child_id=child.order_id, oms=oms, book=sess.book
                )
        self._resolve(oms, req)

    def _resolve(self, oms, req):
        status = oms.status(req.order_id)
        if status in (OrderStatus.SUBMITTED, OrderStatus.ACKNOWLEDGED):
            oms.reject(req.order_id, "broker_no_fill")  # nothing filled at all
        elif status == OrderStatus.PARTIALLY_FILLED and self.config.cancel_unfilled_remainder:
            oms.confirm_cancel(req.order_id, reason="remainder_cancelled")

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _make_algo(self, name):
        if name == "twap":
            return get_algorithm("twap", n_slices=self.config.twap_slices)
        if name == "pov":
            return get_algorithm("pov", participation_rate=self.config.pov_participation)
        if name == "vwap":
            return get_algorithm("vwap", profile=self.config.vwap_profile)
        return get_algorithm(name)

    @staticmethod
    def _record_reject(sess, req, reason):
        sess.oms.create(req)
        sess.oms.reject(req.order_id, reason)
        sess.rejections.append((req.order_id, req.security_id, req.quantity, reason))
