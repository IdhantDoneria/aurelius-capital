"""Volatility features."""

from __future__ import annotations

import math
import statistics
from decimal import Decimal

from aurelius.features.registry import (
    Category,
    ValidationStatus,
    Window,
    feature,
    simple_returns,
)

_OWNER = "quant-core"
_ANNUALIZE = math.sqrt(252)


@feature(
    name="hist_vol_20",
    category=Category.VOLATILITY,
    description="Annualized 20-day historical volatility of daily returns.",
    formula="stdev(returns[-20:]) * sqrt(252)",
    inputs=("close",),
    min_periods=21,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Realized risk; scales position sizing and risk budgets.",
    expected_behavior="Clusters (high vol follows high vol); mean-reverts over weeks.",
    failure_modes="Backward-looking — underestimates risk right before a regime break.",
    validation_method="Matches numpy std(ddof=1)*sqrt(252) on the same returns to 1e-6.",
)
def hist_vol_20(w: Window) -> Decimal | None:
    rets = simple_returns(w.close[-21:])
    if len(rets) < 2:
        return None
    return Decimal(str(statistics.stdev(rets) * _ANNUALIZE))


@feature(
    name="rolling_std_20",
    category=Category.VOLATILITY,
    description="20-bar rolling standard deviation of close price (level, not returns).",
    formula="stdev(close[-20:])",
    inputs=("close",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Dispersion of price around its recent mean; feeds Bollinger bands.",
    expected_behavior="Rises with trending or volatile prices, near 0 when flat.",
    failure_modes="Scale-dependent (raw price units) — not comparable across symbols.",
    validation_method="Equals sample stdev of last 20 closes.",
)
def rolling_std_20(w: Window) -> Decimal | None:
    if len(w.close) < 20:
        return None
    vals = [float(c) for c in w.close[-20:]]
    return Decimal(str(statistics.stdev(vals)))


@feature(
    name="atr_14",
    category=Category.VOLATILITY,
    description="14-bar Average True Range (mean of true ranges).",
    formula="mean(TR[-14:]), TR = max(H-L, |H-C_prev|, |L-C_prev|)",
    inputs=("high", "low", "close"),
    min_periods=15,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Typical bar range including gaps; a robust stop-distance / risk unit.",
    expected_behavior="Expands in volatile regimes; used to normalize stops and sizing.",
    failure_modes="Raw-price units → not cross-sectionally comparable; SMA (not Wilder) here.",
    validation_method="TR of a bar with a gap up exceeds its high-low range.",
)
def atr_14(w: Window) -> Decimal | None:
    if len(w.close) < 15:
        return None
    trs: list[Decimal] = []
    for i in range(len(w.close) - 14, len(w.close)):
        prev_close = w.close[i - 1]
        tr = max(
            w.high[i] - w.low[i],
            abs(w.high[i] - prev_close),
            abs(w.low[i] - prev_close),
        )
        trs.append(tr)
    return sum(trs) / Decimal(14)
