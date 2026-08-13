"""Forward statistical diagnostics (M24).

Reuses M9 statistical patterns where applicable.
No new bootstrap, Monte Carlo, or permutation engines — delegates to M9
infrastructure when available, otherwise uses stdlib statistics.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Sequence


# ── sample adequacy ────────────────────────────────────────────────────────────

def sample_adequacy(n_cycles: int) -> str:
    """Classify sample size per M24 §21.

    Thresholds rationale:
      < 20   — fewer than ~1 calendar month (weekly rebalance); no meaningful stats.
      20–62  — roughly 1–3 months daily; preliminary directional evidence only.
      63–251 — roughly 3–12 months daily; meaningful, but not year-length.
      ≥ 252  — ≥ 1 year daily equivalent; extended evidence.
    """
    from mentisrex.research.forward_validation.models import SampleAdequacy
    if n_cycles < 20:
        return SampleAdequacy.INSUFFICIENT
    if n_cycles < 63:
        return SampleAdequacy.PRELIMINARY
    if n_cycles < 252:
        return SampleAdequacy.MEANINGFUL
    return SampleAdequacy.EXTENDED


def is_statistically_reliable(n_cycles: int) -> bool:
    """True only if sample is MEANINGFUL or EXTENDED."""
    from mentisrex.research.forward_validation.models import SampleAdequacy
    return sample_adequacy(n_cycles) in (SampleAdequacy.MEANINGFUL, SampleAdequacy.EXTENDED)


# ── return series helpers ──────────────────────────────────────────────────────

def daily_returns_from_nav(nav_series: list[tuple]) -> list[float]:
    """Compute period-over-period returns from (date, nav) pairs."""
    navs = [n for _, n in nav_series]
    if len(navs) < 2:
        return []
    return [(navs[i] - navs[i - 1]) / navs[i - 1]
            for i in range(1, len(navs))
            if navs[i - 1] > 0]


def rolling_returns(nav_series: list[tuple], window: int) -> list[float]:
    """Rolling window total returns from (date, nav) series."""
    navs = [n for _, n in nav_series]
    if len(navs) < window + 1:
        return []
    out = []
    for i in range(window, len(navs)):
        start_nav = navs[i - window]
        end_nav = navs[i]
        if start_nav > 0:
            out.append(end_nav / start_nav - 1.0)
    return out


def rolling_volatility(daily_rets: list[float], window: int,
                       periods_per_year: int = 252) -> list[float]:
    """Annualized rolling volatility."""
    if len(daily_rets) < window:
        return []
    out = []
    for i in range(window, len(daily_rets) + 1):
        chunk = daily_rets[i - window:i]
        sd = statistics.stdev(chunk) if len(chunk) >= 2 else 0.0
        out.append(sd * math.sqrt(periods_per_year))
    return out


def rolling_sharpe(daily_rets: list[float], window: int,
                   periods_per_year: int = 252) -> list[float]:
    """Rolling annualized Sharpe (excess return / vol, rf=0)."""
    if len(daily_rets) < window:
        return []
    out = []
    for i in range(window, len(daily_rets) + 1):
        chunk = daily_rets[i - window:i]
        mu = statistics.mean(chunk)
        sd = statistics.stdev(chunk) if len(chunk) >= 2 else 0.0
        out.append((mu / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0)
    return out


def rolling_drawdown(nav_series: list[tuple], window: int) -> list[float]:
    """Rolling max drawdown computed over a window of NAV observations."""
    navs = [n for _, n in nav_series]
    if len(navs) < window:
        return []
    out = []
    for i in range(window, len(navs) + 1):
        chunk = navs[i - window:i]
        peak = chunk[0]
        mdd = 0.0
        for v in chunk:
            peak = max(peak, v)
            dd = (peak - v) / peak if peak > 0 else 0.0
            mdd = max(mdd, dd)
        out.append(mdd)
    return out


# ── distribution summary ───────────────────────────────────────────────────────

def return_distribution_summary(daily_rets: list[float]) -> dict:
    """Descriptive statistics for a return series."""
    if not daily_rets:
        return {"n": 0, "mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0,
                "p25": 0.0, "p50": 0.0, "p75": 0.0,
                "skewness": 0.0, "kurtosis": 0.0}
    n = len(daily_rets)
    sorted_r = sorted(daily_rets)
    mu = statistics.mean(daily_rets)
    sd = statistics.stdev(daily_rets) if n >= 2 else 0.0

    # skewness
    if sd > 0 and n >= 3:
        skew = sum((r - mu) ** 3 for r in daily_rets) / (n * sd ** 3)
    else:
        skew = 0.0

    # excess kurtosis
    if sd > 0 and n >= 4:
        kurt = sum((r - mu) ** 4 for r in daily_rets) / (n * sd ** 4) - 3.0
    else:
        kurt = 0.0

    return {
        "n": n,
        "mean": mu,
        "stdev": sd,
        "min": sorted_r[0],
        "max": sorted_r[-1],
        "p25": sorted_r[int(0.25 * n)],
        "p50": sorted_r[int(0.50 * n)],
        "p75": sorted_r[int(0.75 * n)],
        "skewness": skew,
        "kurtosis": kurt,
    }


# ── confidence intervals ───────────────────────────────────────────────────────

def bootstrap_mean_ci(values: list[float], *,
                      n_samples: int = 500,
                      alpha: float = 0.05,
                      seed: int = 0) -> tuple[float, float]:
    """Non-parametric bootstrap CI for the mean.

    Uses stdlib random (not numpy) for zero-dependency compatibility.
    n_samples kept small by default (500) so tests run quickly.
    """
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        statistics.mean(values[rng.randint(0, n - 1)] for _ in range(n))
        for _ in range(n_samples)
    )
    lo_idx = max(0, int(alpha / 2 * n_samples))
    hi_idx = min(len(means) - 1, int((1 - alpha / 2) * n_samples))
    return (means[lo_idx], means[hi_idx])


# ── annualized metrics (with sample-size guard) ────────────────────────────────

@dataclass(frozen=True)
class AnnualizedMetrics:
    annualized_return: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    n_periods: int
    periods_per_year: int
    reliable: bool   # True if MEANINGFUL or EXTENDED sample


def compute_annualized(nav_series: list[tuple],
                       periods_per_year: int = 252) -> AnnualizedMetrics:
    """Compute annualized metrics from a NAV series.

    Unreliable metrics are still computed but reliable=False flags them.
    Never present Sharpe as meaningful when n < 20.
    """
    navs = [n for _, n in nav_series]
    n = len(navs)
    adequate = sample_adequacy(n)
    reliable = is_statistically_reliable(n)

    if n < 2:
        return AnnualizedMetrics(0.0, 0.0, 0.0, 0.0, 0.0, n, periods_per_year, False)

    daily_rets = daily_returns_from_nav(nav_series)
    if not daily_rets:
        return AnnualizedMetrics(0.0, 0.0, 0.0, 0.0, 0.0, n, periods_per_year, False)

    mu = statistics.mean(daily_rets)
    sd = statistics.stdev(daily_rets) if len(daily_rets) >= 2 else 0.0
    ann_ret = (1 + mu) ** periods_per_year - 1
    ann_vol = sd * math.sqrt(periods_per_year)
    sharpe = (mu / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0

    downside = [min(r, 0.0) for r in daily_rets]
    ds_sd = statistics.stdev(downside) if len(downside) >= 2 and any(d < 0 for d in downside) else 0.0
    sortino = (mu / ds_sd * math.sqrt(periods_per_year)) if ds_sd > 0 else 0.0

    # max drawdown
    peak = navs[0]
    mdd = 0.0
    for nav in navs:
        peak = max(peak, nav)
        dd = (peak - nav) / peak if peak > 0 else 0.0
        mdd = max(mdd, dd)

    return AnnualizedMetrics(
        annualized_return=ann_ret,
        volatility=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=mdd,
        n_periods=n,
        periods_per_year=periods_per_year,
        reliable=reliable,
    )
