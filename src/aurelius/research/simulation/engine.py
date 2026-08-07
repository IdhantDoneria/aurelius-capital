"""Portfolio Simulation Engine (AIDP Phase 11).

Evolves optimized portfolios into a multi-year investment history. It never reruns
research: an injected `target_provider(date) -> {security_id: weight}` yields the
already-optimized (Phase 10) portfolio, and a `price_provider(security_id, date)`
supplies PIT marks. Deterministic (no RNG), dependency-injected (execution model,
rebalance policy, providers), and additive.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime

import numpy as np

from aurelius.research.simulation import analytics, attribution as attr_mod, exposure as exp_mod
from aurelius.research.simulation.execution import CostExecutionModel, ExecutionModel
from aurelius.research.simulation.models import (
    EquityPoint,
    PortfolioSnapshot,
    RebalanceEvent,
    SimulationMetadata,
    SimulationResult,
    Trade,
)
from aurelius.research.simulation.orders import SizingConfig, generate_orders
from aurelius.research.simulation.performance import build_summary, drawdown
from aurelius.research.simulation.rebalancing import RebalancePolicy
from aurelius.research.simulation.state import PortfolioState


@dataclass
class SimulationConfig:
    initial_capital: float = 1_000_000.0
    sizing: SizingConfig = field(default_factory=SizingConfig)
    periods_per_year: int = 252


class PortfolioSimulationEngine:
    def __init__(self, *, config: SimulationConfig | None = None,
                 execution_model: ExecutionModel | None = None,
                 policy: RebalancePolicy | None = None, cost_model=None) -> None:
        self.config = config or SimulationConfig()
        if execution_model is None:
            execution_model = CostExecutionModel(cost_model) if cost_model is not None else None
        self.execution = execution_model
        self.policy = policy or RebalancePolicy()

    def run(self, timeline: list[date], target_provider, price_provider, *,
            adv_provider=None, sectors: dict | None = None) -> SimulationResult:
        if self.execution is None:
            raise ValueError("an execution_model (or cost_model) must be injected")
        cfg = self.config
        self._adv = adv_provider                     # used by capacity report in assembly
        state = PortfolioState(cfg.initial_capital)

        equity, snapshots, trades, rebals = [], [], [], []
        weight_hist, price_hist = [], []
        last: date | None = None
        total_cost = 0.0

        for d in timeline:
            tgt = target_provider(d) or {}
            cand = set(state.holdings) | set(tgt)
            prices = {}
            for sid in cand:
                p = price_provider(sid, d)
                if p is not None and p > 0:
                    prices[sid] = float(p)
            state.mark(prices)

            cur_w = state.weights()
            due = self.policy.due(as_of=d, last=last, current=list(cur_w.values()),
                                  target=list(tgt.values()) if tgt else None)
            if due and tgt:
                orders = generate_orders(tgt, state, prices, cfg.sizing)
                day_cost = 0.0
                for o in orders:
                    p = prices.get(o.security_id)
                    adv = adv_provider(o.security_id, d) if adv_provider else None
                    fill = self.execution.execute(o, p, adv)
                    state.apply_fill(fill.security_id, fill.quantity, fill.price, fill.cost, when=d)
                    trades.append(Trade(o.security_id, fill.quantity, fill.price, fill.cost,
                                        fill.notional, date=d))
                    day_cost += fill.cost
                v = state.total_value()
                turned = sum(abs(o.quantity) * prices.get(o.security_id, 0.0) for o in orders)
                rebals.append(RebalanceEvent(d, len(orders), turned / v if v > 0 else 0.0,
                                             day_cost, "due"))
                total_cost += day_cost
                last = d

            v = state.total_value()
            e = state.exposures()
            equity.append(EquityPoint(d, v, state.cash, e["gross"], e["net"]))
            w = state.weights()
            snapshots.append(PortfolioSnapshot(d, v, state.cash, w, e["gross"], e["net"],
                                               e["long"], e["short"], len(w)))
            weight_hist.append(w)
            price_hist.append(prices)

        return self._assemble(state, equity, snapshots, trades, rebals, weight_hist,
                              price_hist, total_cost, timeline, sectors)

    # ── assembly ─────────────────────────────────────────────────────────────

    def _assemble(self, state, equity, snapshots, trades, rebals, weight_hist,
                  price_hist, total_cost, timeline, sectors) -> SimulationResult:
        cfg = self.config
        values = [e.value for e in equity]
        start, end = (timeline[0], timeline[-1]) if timeline else (None, None)
        n_years = max((end - start).days / 365.25, 1e-9) if start and end else 1e-9
        avg_value = float(np.mean(values)) if values else cfg.initial_capital
        exp_rep = exp_mod.exposure_report(snapshots)
        turn_rep = analytics.turnover_report(trades, avg_value, n_years=n_years,
                                             n_trades=len(trades),
                                             avg_holding_days=_avg_holding(rebals, timeline))
        cost_rep = analytics.cost_report(trades, initial_capital=cfg.initial_capital, n_years=n_years)
        cap_rep = analytics.capacity_report(trades, getattr(self, "_adv", None))
        dd_rep = drawdown(values)
        risk_tl = exp_mod.risk_timeline(snapshots, values, periods=cfg.periods_per_year)
        summary = build_summary(values, n_rebalances=len(rebals),
                                annualized_turnover=turn_rep.annualized_turnover,
                                avg_holding_days=turn_rep.avg_holding_days,
                                total_cost=total_cost, cost_drag_annualized=cost_rep.cost_drag_annualized,
                                periods=cfg.periods_per_year, n_years=n_years)
        attribution = attr_mod.attribution(
            weight_history=weight_hist, price_history=price_hist, total_cost=total_cost,
            initial_capital=cfg.initial_capital, total_return=summary.total_return,
            avg_cash_weight=exp_rep.avg_cash_weight, sectors=sectors)

        meta = SimulationMetadata(
            initial_capital=cfg.initial_capital, start_date=start, end_date=end,
            n_periods=len(timeline), n_rebalances=len(rebals),
            rebalance_policy=("explicit" if self.policy.explicit is not None
                              else (self.policy.rule.mode if self.policy.rule else "every_period")),
            execution_model=self.execution.name, cost_model={},
            allow_short=cfg.sizing.allow_short, config={"sizing": asdict(cfg.sizing)})

        return SimulationResult(
            summary=summary, metadata=meta, equity_curve=equity, snapshots=snapshots,
            rebalance_events=rebals, trades=trades, cost_report=cost_rep,
            turnover_report=turn_rep, exposure_report=exp_rep, drawdown_report=dd_rep,
            capacity_report=cap_rep, risk_timeline=risk_tl, attribution=attribution,
            diagnostics={"ledger_reconciles": state.ledger.reconciles(),
                         "realized_pnl": state.realized_pnl_total,
                         "unrealized_pnl": state.unrealized_pnl(),
                         "final_cash": state.cash, "n_trades": len(trades)},
            generated_at=datetime.now(UTC))


def _avg_holding(rebals, timeline) -> float:
    """Turnover-proxy average holding period (documented approximation)."""
    if not rebals or not timeline:
        return 0.0
    total_turn = sum(r.turnover for r in rebals)
    days = (timeline[-1] - timeline[0]).days or 1
    return days / max(total_turn, 1e-9) if total_turn > 0 else float(days)
