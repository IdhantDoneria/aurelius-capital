"""Statistical testing engine — no numpy/scipy; stdlib only.

StatEngine provides:
  bootstrap_sharpe_ci   — block bootstrap CI for annualized Sharpe
  permutation_pvalue    — shuffle-test null: no alpha beyond vol structure
  bh_fdr               — Benjamini-Hochberg FDR correction
  sharpe_from_returns   — helper used by bootstrap/permutation loops
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass


@dataclass
class BootstrapResult:
    observed: float
    ci_lower: float
    ci_upper: float
    ci_level: float
    n_samples: int
    bias: float  # bootstrap mean - observed


@dataclass
class PermutationResult:
    observed_sharpe: float
    pvalue: float
    n_permutations: int


def _annualized_sharpe(returns: list[float], rf_daily: float, td: int) -> float:
    if len(returns) < 2:
        return 0.0
    m = statistics.mean(returns)
    s = statistics.stdev(returns)
    if s == 0:
        return 0.0
    return (m - rf_daily) / s * math.sqrt(td)


class StatEngine:
    def __init__(
        self,
        risk_free_rate: float = 0.05,
        trading_days: int = 252,
        seed: int = 42,
    ) -> None:
        self._rf_daily = (1 + risk_free_rate) ** (1.0 / trading_days) - 1
        self._td = trading_days
        self._rng = random.Random(seed)

    # ── bootstrap ─────────────────────────────────────────────────────────────

    def bootstrap_sharpe_ci(
        self,
        daily_returns: list[float],
        n: int = 2000,
        ci: float = 0.95,
        block_size: int = 10,
    ) -> BootstrapResult:
        """Block bootstrap CI for annualized Sharpe.

        Block bootstrap (vs IID) preserves autocorrelation in returns —
        important for strategies with momentum/mean-reversion in fills.
        block_size=10 (2 weeks) covers most short-horizon autocorrelation.
        """
        observed = _annualized_sharpe(daily_returns, self._rf_daily, self._td)
        if len(daily_returns) < 2 * block_size:
            return BootstrapResult(observed, observed, observed, ci, n, 0.0)

        n_blocks = math.ceil(len(daily_returns) / block_size)
        bootstrapped: list[float] = []
        for _ in range(n):
            sample: list[float] = []
            for _ in range(n_blocks):
                start = self._rng.randint(0, len(daily_returns) - block_size)
                sample.extend(daily_returns[start : start + block_size])
            sample = sample[: len(daily_returns)]
            bootstrapped.append(_annualized_sharpe(sample, self._rf_daily, self._td))

        bootstrapped.sort()
        alpha = 1 - ci
        lo_idx = int(alpha / 2 * n)
        hi_idx = int((1 - alpha / 2) * n)
        bias = statistics.mean(bootstrapped) - observed
        return BootstrapResult(
            observed=observed,
            ci_lower=bootstrapped[lo_idx],
            ci_upper=bootstrapped[min(hi_idx, n - 1)],
            ci_level=ci,
            n_samples=n,
            bias=bias,
        )

    # ── Monte Carlo significance test ─────────────────────────────────────────

    def permutation_pvalue(
        self,
        daily_returns: list[float],
        n: int = 2000,
    ) -> PermutationResult:
        """Monte Carlo test under the null of zero mean return.

        Sharpe is order-invariant, so permuting returns is meaningless
        (every shuffle yields the same Sharpe). Instead: generate n synthetic
        series from N(mean=0, vol=observed_vol) — the null that there is no
        alpha beyond random volatility — and count how often null Sharpe
        exceeds the observed Sharpe. p-value = P(null >= observed).

        Small p-value: observed Sharpe is unlikely under zero-mean noise alone.
        """
        observed = _annualized_sharpe(daily_returns, self._rf_daily, self._td)
        if len(daily_returns) < 4:
            return PermutationResult(observed, 1.0, n)

        try:
            std = statistics.stdev(daily_returns)
        except statistics.StatisticsError:
            return PermutationResult(observed, 1.0, n)
        if std == 0:
            return PermutationResult(observed, 1.0, n)

        count_ge = 0
        for _ in range(n):
            null_returns = [self._rng.gauss(0.0, std) for _ in range(len(daily_returns))]
            if _annualized_sharpe(null_returns, self._rf_daily, self._td) >= observed:
                count_ge += 1
        return PermutationResult(
            observed_sharpe=observed,
            pvalue=count_ge / n,
            n_permutations=n,
        )

    # ── multiple testing corrections ──────────────────────────────────────────

    @staticmethod
    def bonferroni(pvalue: float, n_trials: int) -> float:
        """Bonferroni correction. Conservative; use BH for many simultaneous tests."""
        return min(1.0, pvalue * max(n_trials, 1))

    @staticmethod
    def bh_fdr(pvalues: list[float], alpha: float = 0.05) -> tuple[list[float], list[bool]]:
        """Benjamini-Hochberg FDR correction.

        Less conservative than Bonferroni when many tests share a common null.
        Returns (adjusted_pvalues, rejected_flags).
        """
        n = len(pvalues)
        if n == 0:
            return [], []
        ranked = sorted(enumerate(pvalues), key=lambda x: x[1])
        adj = [1.0] * n
        rejected = [False] * n
        prev_adj = 1.0
        for rev_rank, (orig_i, p) in enumerate(reversed(ranked)):
            rank = n - rev_rank  # 1-based rank from largest p
            a = min(prev_adj, p * n / rank)
            adj[orig_i] = a
            prev_adj = a
        for i, a in enumerate(adj):
            rejected[i] = a <= alpha
        return adj, rejected

    # ── confidence interval from z-stat ──────────────────────────────────────

    @staticmethod
    def sharpe_se(sharpe_ann: float, n_obs: int, trading_days: int = 252) -> float:
        """Asymptotic standard error of annualized Sharpe estimator.

        SE(SR_annual) ≈ sqrt((1 + 0.5*SR_daily^2) / n) * sqrt(trading_days)
        from Lo (2002), "The Statistics of Sharpe Ratios".
        """
        if n_obs < 4:
            return float("inf")
        sr_daily = sharpe_ann / math.sqrt(trading_days)
        se_daily = math.sqrt((1 + 0.5 * sr_daily**2) / n_obs)
        return se_daily * math.sqrt(trading_days)

    @staticmethod
    def sharpe_z_ci(
        sharpe_ann: float, n_obs: int, ci: float = 0.95, trading_days: int = 252
    ) -> tuple[float, float]:
        """Closed-form CI for annualized Sharpe (Lo 2002). Faster than bootstrap for large n."""
        se = StatEngine.sharpe_se(sharpe_ann, n_obs, trading_days)
        z = _norm_ppf((1 + ci) / 2)
        return sharpe_ann - z * se, sharpe_ann + z * se


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF via rational approximation (Abramowitz & Stegun 26.2.17)."""
    if p <= 0:
        return float("-inf")
    if p >= 1:
        return float("inf")
    if p < 0.5:
        return -_norm_ppf(1 - p)
    t = math.sqrt(-2 * math.log(1 - p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t**2) / (1 + d1 * t + d2 * t**2 + d3 * t**3)
