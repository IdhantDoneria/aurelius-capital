"""PortfolioBuilder — the Phase-8 pipeline and the seam to the rest of the system.

    signals -> aggregate alpha -> size/optimize weights -> exposure overlay
            -> target weights -> delta orders vs current book
            -> RiskEngine screen -> execution list

Integration seams:
  Backtesting : consumes PortfolioState (current book, NAV, marks) and emits
                OrderEvent objects the engine already knows how to execute.
  Risk        : every delta order is screened by the Phase-7 RiskEngine; a
                MODIFY clamps the quantity, a REJECT drops the order. Portfolio
                construction proposes; risk disposes. No order bypasses it.
  Execution   : TargetPortfolio.orders is exactly what the execution layer fills.

Covariance is annualized (Sigma_daily * 252) so vol targets read as annual vol.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import numpy as np

from aurelius.backtesting.events.types import OrderEvent, OrderType, Side
from aurelius.backtesting.portfolio.state import PortfolioState
from aurelius.construction import optimize, sizing
from aurelius.construction.aggregation import RawSignal, SignalAggregator
from aurelius.construction.exposure import ExposureLimits, apply_limits
from aurelius.risk import OrderContext, RiskDecision, RiskEngine


class Method(enum.StrEnum):
    EQUAL_WEIGHT = "equal_weight"
    VOL_TARGET = "vol_target"
    RISK_PARITY = "risk_parity"
    MIN_VARIANCE = "min_variance"
    MAX_SHARPE = "max_sharpe"
    CONSTRAINED = "constrained"  # constrained (box) minimum variance


@dataclass
class TargetPortfolio:
    weights: dict[str, float]  # final target weights (of NAV)
    orders: list[OrderEvent] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (symbol, reason)


class PortfolioBuilder:
    def __init__(
        self,
        method: Method = Method.VOL_TARGET,
        limits: ExposureLimits | None = None,
        risk_engine: RiskEngine | None = None,
        target_vol: float = 0.10,
        aggregator: SignalAggregator | None = None,
    ) -> None:
        self._method = method
        self._limits = limits or ExposureLimits()
        self._risk = risk_engine or RiskEngine()
        self._target_vol = target_vol
        self._agg = aggregator or SignalAggregator()

    def build(
        self,
        signals: list[RawSignal],
        returns: dict[str, list[float]],
        prices: dict[str, Decimal],
        state: PortfolioState,
        sector_map: dict[str, str] | None = None,
        adv: dict[str, Decimal] | None = None,
    ) -> TargetPortfolio:
        alpha = self._agg.combine(signals)
        syms, sigma_d = optimize.sample_covariance(returns)
        sigma = sigma_d * 252.0  # annualize
        weights = self._weights(alpha, syms, sigma)

        avg_corr = _avg_abs_correlation(sigma)
        weights = apply_limits(weights, self._limits, sector_map, avg_corr)

        tp = TargetPortfolio(weights=weights)
        self._make_orders(tp, weights, prices, state, adv)
        return tp

    # ── weight construction per method ─────────────────────────────────────────

    def _weights(
        self, alpha: dict[str, float], syms: list[str], sigma: np.ndarray
    ) -> dict[str, float]:
        m = self._method
        if m is Method.EQUAL_WEIGHT:
            return sizing.equal_weight(alpha)

        vols = {s: float(np.sqrt(sigma[i, i])) for i, s in enumerate(syms)}
        if m is Method.VOL_TARGET:
            return sizing.volatility_target(alpha, vols, self._target_vol, (syms, sigma))
        if m is Method.RISK_PARITY:
            sel = [s for s in syms if alpha.get(s, 0.0) != 0.0]
            sub = _submatrix(syms, sigma, sel)
            return sizing.risk_parity(sel, sub, alpha)

        # Optimizer methods work over the covariance universe. alpha is the return
        # view for max_sharpe; min_variance/constrained ignore it (documented).
        sel = [s for s in syms if alpha.get(s, 0.0) != 0.0] or syms
        sub = _submatrix(syms, sigma, sel)
        if m is Method.MAX_SHARPE:
            mu = np.array([alpha.get(s, 0.0) for s in sel])
            w = optimize.max_sharpe(mu, sub)
        elif m is Method.CONSTRAINED:
            w = optimize.constrained_min_variance(sub, lo=0.0, hi=self._limits.max_asset_weight)
        else:  # MIN_VARIANCE
            w = optimize.min_variance(sub)
        return {s: float(w[i]) for i, s in enumerate(sel)}

    # ── weights -> orders, each screened by the risk engine ─────────────────────

    def _make_orders(
        self,
        tp: TargetPortfolio,
        weights: dict[str, float],
        prices: dict[str, Decimal],
        state: PortfolioState,
        adv: dict[str, Decimal] | None,
    ) -> None:
        nav = state.total_value
        for sym, w in weights.items():
            price = prices.get(sym, Decimal("0"))
            if price <= 0:
                continue
            target_qty = Decimal(int((nav * Decimal(str(w))) / price))
            pos = state.positions.get(sym)
            cur_qty = pos.quantity if pos else Decimal("0")
            delta = target_qty - cur_qty
            if delta == 0:
                continue

            is_buy = delta > 0
            ctx = OrderContext(
                symbol=sym,
                price=price,
                quantity=abs(delta),
                is_buy=is_buy,
                adv=adv.get(sym) if adv else None,
            )
            verdict = self._risk.evaluate(ctx, state)
            if verdict.decision is RiskDecision.REJECT:
                tp.rejected.append((sym, "; ".join(verdict.reasons)))
                continue
            qty = verdict.modified_quantity if verdict.modified_quantity is not None else abs(delta)
            if qty <= 0:
                continue
            tp.orders.append(
                OrderEvent(
                    timestamp=datetime.now(UTC),
                    symbol=sym,
                    order_type=OrderType.MARKET,
                    side=Side.BUY if is_buy else Side.SELL,
                    quantity=qty,
                    strategy_id="portfolio_builder",
                )
            )


def _submatrix(syms: list[str], sigma: np.ndarray, sel: list[str]) -> np.ndarray:
    idx = [syms.index(s) for s in sel]
    return sigma[np.ix_(idx, idx)] if idx else np.zeros((0, 0))


def _avg_abs_correlation(sigma: np.ndarray) -> float:
    """Mean |rho| over off-diagonal entries of the correlation matrix from Sigma."""
    n = sigma.shape[0]
    if n < 2:
        return 0.0
    d = np.sqrt(np.clip(np.diag(sigma), 1e-18, None))
    corr = sigma / np.outer(d, d)
    off = corr[~np.eye(n, dtype=bool)]
    return float(np.mean(np.abs(off)))
