"""Robustness analysis — does the edge survive when assumptions change?

RobustnessAnalyzer evaluates:
  1. Regime analysis      — performance across bull/bear/neutral equity-curve regimes
  2. TC sensitivity       — Sharpe as transaction cost varies; breakeven TC
  3. Slippage sensitivity — same sweep for slippage
  4. Walk-forward consistency — CV of per-fold Sharpes from research.validation
  5. Rolling stability    — is performance monotonically declining (signal decay)?

All inputs are in-memory (no DB calls). Bars are not required — analysis uses
the equity curve and daily returns from a completed backtest.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from mentisrex.backtesting.analytics.performance import EquityPoint


@dataclass
class RegimeStats:
    label: str  # "bull", "bear", "neutral"
    n_days: int
    sharpe: float
    total_return: float
    max_drawdown: float


@dataclass
class SensitivitySweep:
    """Sharpe as one cost parameter varies."""

    param_name: str  # "tc_bps" or "slippage_bps"
    values: list[float]  # cost levels tested
    sharpes: list[float]  # Sharpe at each level
    breakeven: float  # cost level where Sharpe crosses 0 (or -1 if never)
    degradation_per_bps: float  # average dSharpe/dbps across the sweep


@dataclass
class RobustnessAssessment:
    is_robust: bool

    regime_stats: list[RegimeStats]
    regime_consistent: bool  # positive Sharpe in >=2 of 3 regimes

    tc_sweep: SensitivitySweep
    slippage_sweep: SensitivitySweep

    walk_forward_sharpes: list[float]
    walk_forward_cv: float  # abs(stdev / mean); low = consistent
    worst_fold_sharpe: float
    best_fold_sharpe: float
    walk_forward_consistent: bool  # all folds positive (or majority positive)

    rolling_stable: bool  # rolling metric not monotonically declining
    rolling_sharpes: list[float]

    weaknesses: list[str]
    strengths: list[str]


def _regime_label(rolling_equity_slope: float, threshold: float = 0.001) -> str:
    if rolling_equity_slope > threshold:
        return "bull"
    if rolling_equity_slope < -threshold:
        return "bear"
    return "neutral"


def _slice_sharpe(daily_returns: list[float], rf_daily: float, td: int) -> float:
    if len(daily_returns) < 2:
        return 0.0
    m = statistics.mean(daily_returns)
    s = statistics.stdev(daily_returns)
    if s == 0:
        return 0.0
    return (m - rf_daily) / s * math.sqrt(td)


def _slice_total_return(equity_slice: list[float]) -> float:
    if len(equity_slice) < 2 or equity_slice[0] == 0:
        return 0.0
    return equity_slice[-1] / equity_slice[0] - 1.0


def _slice_max_dd(equity_slice: list[float]) -> float:
    peak = equity_slice[0]
    max_dd = 0.0
    for eq in equity_slice:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _cost_adjusted_sharpe(
    daily_returns: list[float],
    annual_turnover: float,
    extra_cost_bps: float,
    rf_daily: float,
    td: int,
) -> float:
    """Approximate Sharpe after adding extra_cost_bps of annual cost.

    Extra drag per day = extra_cost_bps / 10000 * annual_turnover / td.
    Applied as a constant daily deduction from returns.
    """
    daily_drag = (extra_cost_bps / 10_000.0) * annual_turnover / td
    adjusted = [r - daily_drag for r in daily_returns]
    return _slice_sharpe(adjusted, rf_daily, td)


def _breakeven_cost(
    daily_returns: list[float],
    annual_turnover: float,
    rf_daily: float,
    td: int,
    max_search_bps: float = 500.0,
) -> float:
    """Binary search for the extra cost (bps) that drives Sharpe to 0."""
    if _cost_adjusted_sharpe(daily_returns, annual_turnover, 0, rf_daily, td) <= 0:
        return 0.0
    lo, hi = 0.0, max_search_bps
    for _ in range(30):
        mid = (lo + hi) / 2
        if _cost_adjusted_sharpe(daily_returns, annual_turnover, mid, rf_daily, td) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.1:
            break
    return (lo + hi) / 2


class RobustnessAnalyzer:
    def __init__(
        self,
        risk_free_rate: float = 0.05,
        trading_days: int = 252,
        regime_window: int = 63,  # ~3 months
    ) -> None:
        self._rf_daily = (1 + risk_free_rate) ** (1.0 / trading_days) - 1
        self._td = trading_days
        self._regime_win = regime_window

    def analyze(
        self,
        daily_returns: list[float],
        equity_curve: list[EquityPoint],
        annual_turnover: float,
        walk_forward_sharpes: list[float],
        rolling_metric: list[float] | None = None,
        tc_sweep_range: list[float] | None = None,
        slip_sweep_range: list[float] | None = None,
    ) -> RobustnessAssessment:
        if tc_sweep_range is None:
            tc_sweep_range = [0, 5, 10, 20, 30, 50, 75, 100, 150, 200]
        if slip_sweep_range is None:
            slip_sweep_range = [0, 5, 10, 20, 30, 50, 75, 100]

        weaknesses: list[str] = []
        strengths: list[str] = []

        # ── regime analysis ──────────────────────────────────────────────────
        regime_stats = self._regime_analysis(daily_returns, equity_curve)
        positive_regimes = sum(1 for r in regime_stats if r.sharpe > 0)
        regime_consistent = (
            positive_regimes >= max(1, len(regime_stats) // 2 + 1) if regime_stats else False
        )
        if not regime_consistent:
            weaknesses.append(
                f"only {positive_regimes}/{len(regime_stats)} regimes show positive Sharpe"
            )
        else:
            strengths.append(f"positive Sharpe in {positive_regimes}/{len(regime_stats)} regimes")

        # ── TC sweep ─────────────────────────────────────────────────────────
        tc_sweep = self._cost_sweep("tc_bps", daily_returns, annual_turnover, tc_sweep_range)
        if tc_sweep.breakeven < 30:
            weaknesses.append(
                f"TC breakeven only {tc_sweep.breakeven:.0f} bps — fragile to execution costs"
            )
        elif tc_sweep.breakeven > 100:
            strengths.append(f"TC robust: breakeven at {tc_sweep.breakeven:.0f} bps")

        # ── slippage sweep ───────────────────────────────────────────────────
        slip_sweep = self._cost_sweep(
            "slippage_bps", daily_returns, annual_turnover, slip_sweep_range
        )
        if slip_sweep.breakeven < 20:
            weaknesses.append(
                f"slippage breakeven only {slip_sweep.breakeven:.0f} bps — fragile to market impact"
            )

        # ── walk-forward consistency ──────────────────────────────────────────
        wf_consistent = False
        wf_cv = float("inf")
        worst_fold = 0.0
        best_fold = 0.0
        if walk_forward_sharpes:
            worst_fold = min(walk_forward_sharpes)
            best_fold = max(walk_forward_sharpes)
            positive_folds = sum(1 for s in walk_forward_sharpes if s > 0)
            wf_consistent = positive_folds > len(walk_forward_sharpes) / 2
            mean_wf = statistics.mean(walk_forward_sharpes)
            if mean_wf != 0 and len(walk_forward_sharpes) > 1:
                wf_cv = abs(statistics.stdev(walk_forward_sharpes) / mean_wf)
            if not wf_consistent:
                weaknesses.append(
                    f"walk-forward: only {positive_folds}/{len(walk_forward_sharpes)} "
                    f"folds positive"
                )
            elif wf_cv > 1.5:
                weaknesses.append(
                    f"walk-forward inconsistent: CV={wf_cv:.2f} (high variance across folds)"
                )
            else:
                strengths.append(
                    f"walk-forward consistent: {positive_folds}/{len(walk_forward_sharpes)} "
                    f"positive folds"
                )

        # ── rolling stability ─────────────────────────────────────────────────
        rolling = rolling_metric or []
        rolling_stable = True
        if len(rolling) >= 10:
            # Check if last third is below first third (decaying signal)
            third = len(rolling) // 3
            early_mean = statistics.mean(rolling[:third])
            late_mean = statistics.mean(rolling[-third:])
            rolling_stable = late_mean >= early_mean * 0.7  # allow 30% decay
            if not rolling_stable:
                weaknesses.append(
                    f"rolling metric decaying: early={early_mean:.2f} → late={late_mean:.2f}"
                )

        is_robust = (
            regime_consistent and tc_sweep.breakeven >= 20 and wf_consistent and rolling_stable
        )

        return RobustnessAssessment(
            is_robust=is_robust,
            regime_stats=regime_stats,
            regime_consistent=regime_consistent,
            tc_sweep=tc_sweep,
            slippage_sweep=slip_sweep,
            walk_forward_sharpes=walk_forward_sharpes,
            walk_forward_cv=wf_cv,
            worst_fold_sharpe=worst_fold,
            best_fold_sharpe=best_fold,
            walk_forward_consistent=wf_consistent,
            rolling_stable=rolling_stable,
            rolling_sharpes=rolling,
            weaknesses=weaknesses,
            strengths=strengths,
        )

    def _regime_analysis(
        self,
        daily_returns: list[float],
        equity_curve: list[EquityPoint],
    ) -> list[RegimeStats]:
        equities = [p.equity for p in equity_curve]
        [p.timestamp for p in equity_curve]
        n = len(equities)
        if n < self._regime_win * 2:
            return []

        # Classify each day: slope of equity over trailing window
        regime_returns: dict[str, list[float]] = {"bull": [], "bear": [], "neutral": []}
        regime_equities: dict[str, list[float]] = {"bull": [], "bear": [], "neutral": []}

        for i in range(self._regime_win, n):
            window_eq = equities[i - self._regime_win : i]
            slope = (window_eq[-1] - window_eq[0]) / (window_eq[0] if window_eq[0] != 0 else 1)
            label = _regime_label(slope)
            if i - 1 < len(daily_returns):
                regime_returns[label].append(daily_returns[i - 1])
            regime_equities[label].append(equities[i])

        result: list[RegimeStats] = []
        for label in ("bull", "bear", "neutral"):
            rets = regime_returns[label]
            eqs = regime_equities[label]
            if len(rets) < 5:
                continue
            sharpe = _slice_sharpe(rets, self._rf_daily, self._td)
            total_ret = _slice_total_return(eqs) if eqs else 0.0
            max_dd = _slice_max_dd(eqs) if eqs else 0.0
            result.append(RegimeStats(label, len(rets), sharpe, total_ret, max_dd))
        return result

    def _cost_sweep(
        self,
        param_name: str,
        daily_returns: list[float],
        annual_turnover: float,
        sweep_range: list[float],
    ) -> SensitivitySweep:
        sharpes = [
            _cost_adjusted_sharpe(daily_returns, annual_turnover, bps, self._rf_daily, self._td)
            for bps in sweep_range
        ]
        be = _breakeven_cost(daily_returns, annual_turnover, self._rf_daily, self._td)
        # degradation rate: linear regression slope d(Sharpe)/d(bps)
        if len(sweep_range) > 1:
            xs = sweep_range
            ys = sharpes
            mx = statistics.mean(xs)
            my = statistics.mean(ys)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
            den = sum((x - mx) ** 2 for x in xs)
            deg = num / den if den != 0 else 0.0
        else:
            deg = 0.0
        return SensitivitySweep(param_name, sweep_range, sharpes, be, deg)
