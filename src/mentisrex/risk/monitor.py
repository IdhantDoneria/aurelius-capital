"""PortfolioRiskMonitor — read-only measurement of live portfolio risk.

Measures, never trades. Feeds a RiskReport the desk watches on a dashboard and
the engine consults for account-level halts. Every metric is annualized to the
252-day convention where a horizon applies.

Formulas:
  volatility (ann)  : sigma_ann = stdev(daily_returns) * sqrt(252)
  drawdown          : DD_t = (V_t - peak_t)/peak_t ; reported = current DD
  VaR (1-day, param): VaR = z_alpha * sigma_daily * NAV
  sector exposure   : S_k = sum_{i in k} |mv_i| / gross
  Herfindahl        : HHI = sum_i w_i^2  with w_i = |mv_i|/gross
  correlation       : rho_ij = cov(r_i,r_j)/(sigma_i*sigma_j) ; report mean rho
  portfolio beta    : beta_p = sum_i w_i * beta_i (loadings supplied)
"""

from __future__ import annotations

import math
import statistics

from mentisrex.backtesting.portfolio.state import PortfolioState
from mentisrex.risk.models import RiskLimits, RiskReport

_TRADING_DAYS = 252

# Inverse standard-normal CDF at common confidences (one-sided VaR z-scores).
_Z = {0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263}


def _z_score(confidence: float) -> float:
    """Nearest tabulated z; VaR confidence is always one of a few standard values."""
    return _Z[min(_Z, key=lambda c: abs(c - confidence))]


class PortfolioRiskMonitor:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()

    def assess(
        self,
        state: PortfolioState,
        daily_returns: list[float],
        sector_map: dict[str, str] | None = None,
        symbol_returns: dict[str, list[float]] | None = None,
        betas: dict[str, float] | None = None,
    ) -> RiskReport:
        lim = self._limits
        nav = float(state.total_value)
        gross = float(state.gross_exposure)

        vol = self._annualized_vol(daily_returns)
        var = _z_score(lim.var_confidence) * (vol / math.sqrt(_TRADING_DAYS)) * nav

        sectors = self._sector_exposure(state, gross, sector_map)
        hhi = self._herfindahl(state, gross)
        avg_corr = self._avg_correlation(symbol_returns)
        beta = self._portfolio_beta(state, gross, betas)

        breaches: list[str] = []
        if float(state.drawdown) < -float(lim.max_drawdown_halt):
            breaches.append(f"drawdown {state.drawdown:.1%}")
        if float(state.gross_leverage) > float(lim.max_gross_leverage):
            breaches.append(f"gross leverage {state.gross_leverage:.2f}x")
        for sec, w in sectors.items():
            if w > float(lim.max_sector_pct):
                breaches.append(f"sector {sec} {w:.1%}")
        if hhi > float(lim.max_hhi):
            breaches.append(f"HHI {hhi:.3f}")

        return RiskReport(
            annualized_volatility=vol,
            current_drawdown=float(state.drawdown),
            value_at_risk=var,
            gross_leverage=float(state.gross_leverage),
            net_leverage=float(state.net_leverage),
            herfindahl=hhi,
            avg_pairwise_correlation=avg_corr,
            portfolio_beta=beta,
            sector_exposure=sectors,
            breaches=breaches,
        )

    # ── metrics ──────────────────────────────────────────────────────────────

    @staticmethod
    def _annualized_vol(returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        return statistics.stdev(returns) * math.sqrt(_TRADING_DAYS)

    @staticmethod
    def _sector_exposure(
        state: PortfolioState, gross: float, sector_map: dict[str, str] | None
    ) -> dict[str, float]:
        if not sector_map or gross <= 0:
            return {}
        out: dict[str, float] = {}
        for sym, pos in state.positions.items():
            if pos.is_flat:
                continue
            sec = sector_map.get(sym, "UNKNOWN")
            out[sec] = out.get(sec, 0.0) + abs(float(pos.market_value)) / gross
        return out

    @staticmethod
    def _herfindahl(state: PortfolioState, gross: float) -> float:
        if gross <= 0:
            return 0.0
        return sum(
            (abs(float(p.market_value)) / gross) ** 2
            for p in state.positions.values()
            if not p.is_flat
        )

    @staticmethod
    def _avg_correlation(symbol_returns: dict[str, list[float]] | None) -> float:
        """Mean pairwise Pearson correlation. High = diversification breakdown."""
        if not symbol_returns or len(symbol_returns) < 2:
            return 0.0
        series = [r for r in symbol_returns.values() if len(r) >= 2]
        corrs: list[float] = []
        for i in range(len(series)):
            for j in range(i + 1, len(series)):
                n = min(len(series[i]), len(series[j]))
                a, b = series[i][-n:], series[j][-n:]
                try:
                    corrs.append(statistics.correlation(a, b))
                except statistics.StatisticsError:
                    continue  # constant series -> undefined corr, skip
        return statistics.mean(corrs) if corrs else 0.0

    @staticmethod
    def _portfolio_beta(
        state: PortfolioState, gross: float, betas: dict[str, float] | None
    ) -> float | None:
        if not betas or gross <= 0:
            return None
        return sum(
            betas.get(p.symbol, 0.0) * abs(float(p.market_value)) / gross
            for p in state.positions.values()
            if not p.is_flat
        )
