"""Price features. Pure functions over a trailing Window; value for last bar."""

from __future__ import annotations

import math
from decimal import Decimal

from aurelius.features.registry import (
    Category,
    ValidationStatus,
    Window,
    feature,
    pct_change,
)

_OWNER = "quant-core"


@feature(
    name="returns_1d",
    category=Category.PRICE,
    description="1-day simple return of close.",
    formula="(close_t - close_{t-1}) / close_{t-1}",
    inputs=("close",),
    min_periods=2,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Price change is the atom of every return-based signal.",
    expected_behavior="Roughly mean-zero, fat-tailed, near-zero autocorrelation for liquid names.",
    failure_modes="Splits/dividends not adjusted inflate returns; prev close of 0 → undefined.",
    validation_method="Reconcile against exchange-adjusted returns on a known symbol.",
)
def returns_1d(w: Window) -> Decimal | None:
    return pct_change(w.close, 1)


@feature(
    name="log_returns_1d",
    category=Category.PRICE,
    description="1-day log return of close.",
    formula="ln(close_t / close_{t-1})",
    inputs=("close",),
    min_periods=2,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Additive across time; the natural unit for volatility and compounding.",
    expected_behavior="Symmetric, additive over horizons; ~equal to simple return for small moves.",
    failure_modes=(
        "Non-positive prices -> undefined; same corporate-action caveat as simple returns."
    ),
    validation_method="log_return ≈ simple_return for |r| < 5%.",
)
def log_returns_1d(w: Window) -> Decimal | None:
    if len(w.close) < 2 or w.close[-2] <= 0 or w.close[-1] <= 0:
        return None
    return Decimal(str(math.log(float(w.close[-1] / w.close[-2]))))


@feature(
    name="sma_20",
    category=Category.PRICE,
    description="20-bar simple moving average of close.",
    formula="mean(close[-20:])",
    inputs=("close",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Smooths noise to expose the prevailing price level / trend anchor.",
    expected_behavior="Lags price; crossovers with faster averages mark trend changes.",
    failure_modes="Whipsaws in range-bound markets; lag hurts in fast reversals.",
    validation_method="Equals arithmetic mean of last 20 closes.",
)
def sma_20(w: Window) -> Decimal | None:
    if len(w.close) < 20:
        return None
    return sum(w.close[-20:]) / Decimal(20)


@feature(
    name="momentum_21d",
    category=Category.PRICE,
    description="21-trading-day (≈1 month) price momentum.",
    formula="(close_t - close_{t-21}) / close_{t-21}",
    inputs=("close",),
    min_periods=22,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition=(
        "Recent winners tend to keep winning over 1-12 month horizons (momentum premium)."
    ),
    expected_behavior="Positive average premium; crashes sharply after sharp market reversals.",
    failure_modes="Momentum crashes at turning points; short lookbacks pick up reversal instead.",
    validation_method="Sign matches 21-day price direction on a trending series.",
)
def momentum_21d(w: Window) -> Decimal | None:
    return pct_change(w.close, 21)


@feature(
    name="trend_strength_20",
    category=Category.PRICE,
    description="Fraction of the last 20 returns that are positive, centered to [-1, 1].",
    formula="2 * (#up_bars / 20) - 1  over last 20 returns",
    inputs=("close",),
    min_periods=21,
    owner=_OWNER,
    status=ValidationStatus.EXPERIMENTAL,
    economic_intuition="Persistent one-directional drift signals a durable trend vs. noise.",
    expected_behavior="Near 0 in choppy markets, → ±1 in strong sustained trends.",
    failure_modes="Ignores magnitude; a few large moves in the opposite direction are missed.",
    validation_method="All-up series → +1, all-down → -1, alternating → ~0.",
)
def trend_strength_20(w: Window) -> Decimal | None:
    if len(w.close) < 21:
        return None
    ups = sum(1 for a, b in zip(w.close[-21:-1], w.close[-20:], strict=False) if b > a)
    return Decimal(2) * (Decimal(ups) / Decimal(20)) - Decimal(1)
