"""Statistical features. Beta/correlation require a benchmark (Window.market)."""

from __future__ import annotations

import statistics
from decimal import Decimal

from mentisrex.features.registry import (
    Category,
    ValidationStatus,
    Window,
    feature,
    simple_returns,
)

_OWNER = "quant-core"


@feature(
    name="zscore_20",
    category=Category.STATISTICAL,
    description="Z-score of the latest close vs its trailing 20-bar distribution.",
    formula="(close_t - mean(close[-20:])) / stdev(close[-20:])",
    inputs=("close",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="How stretched price is from its own recent mean — a mean-reversion signal.",
    expected_behavior="Oscillates around 0; |z| > 2 flags statistically extreme moves.",
    failure_modes="Assumes stationarity; in a strong trend price stays extended and z stays high.",
    validation_method="Constant series → 0 (guarded); symmetric series → mean 0.",
)
def zscore_20(w: Window) -> Decimal | None:
    if len(w.close) < 20:
        return None
    vals = [float(c) for c in w.close[-20:]]
    sd = statistics.stdev(vals)
    if sd == 0:
        return Decimal(0)
    return Decimal(str((vals[-1] - statistics.mean(vals)) / sd))


@feature(
    name="mean_deviation_20",
    category=Category.STATISTICAL,
    description="Relative deviation of latest close from its 20-bar mean.",
    formula="(close_t - mean(close[-20:])) / mean(close[-20:])",
    inputs=("close",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Scale-free distance from fair value; comparable across symbols.",
    expected_behavior="Mean-reverts toward 0; large magnitudes precede pullbacks.",
    failure_modes="Trends keep it persistently one-signed; mean of 0 → undefined.",
    validation_method="Price above its mean → positive, below → negative.",
)
def mean_deviation_20(w: Window) -> Decimal | None:
    if len(w.close) < 20:
        return None
    m = sum(w.close[-20:]) / Decimal(20)
    if m == 0:
        return None
    return (w.close[-1] - m) / m


@feature(
    name="correlation_60",
    category=Category.STATISTICAL,
    description="60-day return correlation of the symbol with the benchmark.",
    formula="corr(returns_symbol[-60:], returns_market[-60:])",
    inputs=("close", "market"),
    min_periods=61,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Co-movement with the market — a diversification and regime gauge.",
    expected_behavior="Rises toward 1 in risk-off selloffs (correlations spike in crises).",
    failure_modes="Undefined without a benchmark; unstable if either series is flat.",
    validation_method="Symbol == benchmark → 1.0; independent series → ~0.",
)
def correlation_60(w: Window) -> Decimal | None:
    if w.market is None or len(w.close) < 61 or len(w.market) < 61:
        return None
    rs = simple_returns(w.close[-61:])
    rm = simple_returns(w.market[-61:])
    n = min(len(rs), len(rm))
    if n < 2:
        return None
    try:
        return Decimal(str(statistics.correlation(rs[-n:], rm[-n:])))
    except statistics.StatisticsError:
        return None  # zero variance in a leg


@feature(
    name="beta_60",
    category=Category.STATISTICAL,
    description="60-day CAPM beta of the symbol to the benchmark.",
    formula="cov(r_sym, r_mkt) / var(r_mkt) over last 60 returns",
    inputs=("close", "market"),
    min_periods=61,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Market-risk exposure; the hedge ratio to neutralize systematic risk.",
    expected_behavior="~1 for the average large-cap; >1 cyclicals, <1 defensives.",
    failure_modes=(
        "Undefined without benchmark or when market variance is 0; unstable in low-vol regimes."
    ),
    validation_method="Symbol == benchmark -> 1.0; symbol == 2x market moves -> ~2.0.",
)
def beta_60(w: Window) -> Decimal | None:
    if w.market is None or len(w.close) < 61 or len(w.market) < 61:
        return None
    rs = simple_returns(w.close[-61:])
    rm = simple_returns(w.market[-61:])
    n = min(len(rs), len(rm))
    if n < 2:
        return None
    var_m = statistics.pvariance(rm[-n:])
    if var_m == 0:
        return None
    cov = statistics.covariance(rs[-n:], rm[-n:])
    # covariance() uses sample (n-1); pvariance uses n. Rescale to match denominators.
    var_m_sample = statistics.variance(rm[-n:])
    return Decimal(str(cov / var_m_sample))
