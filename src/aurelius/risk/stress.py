"""StressTester — what does the book look like under a bad day that hasn't happened.

Historical vol understates tail risk; stress tests ask "if X, do we survive?"
directly. Each scenario shocks the current positions and recomputes NAV from
first principles (cash + shocked marks), so the answer reflects the actual book.

Scenarios:
  market crash      : p_i -> p_i*(1+s)          [s < 0]; report ΔNAV, new drawdown
  volatility spike  : sigma -> k*sigma;          stressed VaR = z*(k*sigma)*NAV
  liquidity reduction: ADV -> f*ADV;             days-to-unwind at the participation cap
"""

from __future__ import annotations

import math
from decimal import Decimal

from aurelius.backtesting.portfolio.state import PortfolioState
from aurelius.risk.models import RiskLimits, StressResult
from aurelius.risk.monitor import _z_score


class StressTester:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()

    def _shocked_nav(self, state: PortfolioState, shock: float) -> float:
        """Cash + sum(qty_i * price_i*(1+shock)). Longs lose on a crash, shorts gain."""
        cash = float(state.cash)
        mv = sum(float(p.quantity) * float(p.last_price) * (1 + shock)
                 for p in state.positions.values())
        return cash + mv

    def market_crash(self, state: PortfolioState, shock: float = -0.20) -> StressResult:
        nav0 = float(state.total_value)
        nav1 = self._shocked_nav(state, shock)
        peak = max(nav0, float(state._peak_value))
        dd = (nav1 - peak) / peak if peak > 0 else 0.0
        survives = nav1 > 0 and dd > -float(self._limits.max_drawdown_halt)
        return StressResult(
            scenario=f"market_crash({shock:.0%})",
            nav_before=nav0, nav_after=nav1, pnl=nav1 - nav0,
            survives=survives,
            detail=f"post-shock drawdown {dd:.1%}",
        )

    def volatility_spike(
        self, state: PortfolioState, daily_vol: float, k: float = 3.0
    ) -> StressResult:
        """daily_vol is the current 1-day portfolio sigma (fraction).

        VaR scales linearly in sigma, so a k-fold vol spike is a k-fold VaR.
        """
        nav0 = float(state.total_value)
        z = _z_score(self._limits.var_confidence)
        var = z * (k * daily_vol) * nav0
        return StressResult(
            scenario=f"vol_spike({k}x)",
            nav_before=nav0, nav_after=nav0, pnl=0.0,
            stressed_var=var,
            survives=var < nav0,
            detail=f"1-day VaR at {k}x vol = {var:,.0f} ({var / nav0:.1%} NAV)",
        )

    def liquidity_reduction(
        self, state: PortfolioState, adv: dict[str, Decimal], f: float = 0.30
    ) -> StressResult:
        """Days to unwind = max_i qty_i / (participation * f * ADV_i).

        The book can only trade participation*ADV per day; if ADV dries up by (1-f)
        the horizon stretches. We report the worst single-name horizon (the binding one).
        """
        part = float(self._limits.max_participation_pct)
        worst = 0.0
        worst_sym = ""
        for sym, pos in state.positions.items():
            if pos.is_flat:
                continue
            cap = part * f * float(adv.get(sym, Decimal("0")))
            days = math.inf if cap <= 0 else abs(float(pos.quantity)) / cap
            if days > worst:
                worst, worst_sym = days, sym
        nav0 = float(state.total_value)
        return StressResult(
            scenario=f"liquidity_reduction({f:.0%} ADV)",
            nav_before=nav0, nav_after=nav0, pnl=0.0,
            liquidation_days=worst,
            survives=math.isfinite(worst),
            detail=f"worst unwind: {worst_sym} ~{worst:.1f} days" if worst_sym else "no positions",
        )
